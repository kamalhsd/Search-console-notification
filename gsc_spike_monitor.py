import os
import json
import time
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- CONFIGURATION ---
EMAIL_SENDER = 'kamal.bettersea@gmail.com' 
EMAIL_RECEIVER = 'kamal.bettersea@gmail.com'
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')
MIN_AVG_CLICKS = 5
SPIKE_MULTIPLIER = 2.0

# --- BYPASS LIST ---
IGNORE_LIST = [
    'https://andamantourtravelpackage.com/',
    'sc-domain:andamantourtravelpackage.com'
]
# ---------------------

def get_gsc_service():
    scopes = ['https://www.googleapis.com/auth/webmasters.readonly']
    creds_json = json.loads(os.environ.get('GSC_CREDENTIALS'))
    creds = service_account.Credentials.from_service_account_info(creds_json, scopes=scopes)
    return build('webmasters', 'v3', credentials=creds, cache_discovery=False)

def deduplicate_properties(site_list):
    sc_domains = set()
    prefix_sites = []
    filtered_list = []

    for site in site_list:
        if site in IGNORE_LIST:
            continue
        if site.startswith('sc-domain:'):
            sc_domains.add(site.replace('sc-domain:', '').strip('/'))
            filtered_list.append(site)
        else:
            prefix_sites.append(site)

    for site in prefix_sites:
        parsed_url = urlparse(site)
        netloc = parsed_url.netloc.replace('www.', '') 
        if not any(sc_domain in netloc for sc_domain in sc_domains):
            filtered_list.append(site)
            
    return filtered_list

def get_data(service, site_url, start_date, end_date):
    request = {
        'startDate': start_date,
        'endDate': end_date,
        'dimensions': ['page'],
        'rowLimit': 25000
    }
    try:
        response = service.searchanalytics().query(siteUrl=site_url, body=request).execute()
        return {row['keys'][0]: row['clicks'] for row in response.get('rows', [])}
    except Exception as e:
        print(f"Error fetching {site_url}: {e}")
        return {}

def send_email_alert(anomalies):
    if not anomalies:
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECEIVER
    msg['Subject'] = f"GSC Alert: Traffic Spikes Detected on {len(anomalies)} Pages"

    body = "<h3>The following pages saw a 100%+ traffic spike:</h3><table border='1' cellpadding='5' style='border-collapse: collapse;'>"
    body += "<tr><th>Website</th><th>Page URL</th><th>Avg Clicks (Last 28D)</th><th>Recent Clicks</th><th>Growth</th></tr>"
    
    for item in anomalies:
        body += f"<tr><td>{item['site']}</td><td>{item['page']}</td><td>{item['avg_clicks']}</td><td>{item['recent_clicks']}</td><td>{item['growth']}%</td></tr>"
    
    body += "</table>"
    msg.attach(MIMEText(body, 'html'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("Alert email sent successfully.")
    except Exception as e:
        print(f"Failed to send email: {e}")

def main():
    if not os.environ.get('GSC_CREDENTIALS') or not os.environ.get('EMAIL_PASSWORD'):
        raise ValueError("CRITICAL ERROR: GSC_CREDENTIALS or EMAIL_PASSWORD environment variables are missing.")

    service = get_gsc_service()
    
    recent_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    history_start = (datetime.now() - timedelta(days=31)).strftime('%Y-%m-%d')
    history_end = (datetime.now() - timedelta(days=4)).strftime('%Y-%m-%d')

    print(f"Analyzing Recent ({recent_date}) vs Avg ({history_start} to {history_end})...")

    sites_response = service.sites().list().execute()
    raw_site_list = [site['siteUrl'] for site in sites_response.get('siteEntry', [])]
    
    site_list = deduplicate_properties(raw_site_list)
    print(f"Filtered {len(raw_site_list)} raw properties down to {len(site_list)} active domains.")
    
    anomalies = []

    for site_url in site_list:
        print(f"Processing: {site_url}")
        
        recent_data = get_data(service, site_url, recent_date, recent_date)
        history_data = get_data(service, site_url, history_start, history_end)
        
        for page, recent_clicks in recent_data.items():
            total_history_clicks = history_data.get(page, 0)
            avg_clicks = round(total_history_clicks / 28)
            
            if avg_clicks >= MIN_AVG_CLICKS and recent_clicks >= (avg_clicks * SPIKE_MULTIPLIER):
                growth_pct = round(((recent_clicks / avg_clicks) - 1) * 100)
                anomalies.append({
                    'site': site_url,
                    'page': page,
                    'avg_clicks': avg_clicks,
                    'recent_clicks': recent_clicks,
                    'growth': growth_pct
                })
        
        time.sleep(1)

    if anomalies:
        send_email_alert(anomalies)
    else:
        print("No spikes detected today.")

if __name__ == '__main__':
    main()
