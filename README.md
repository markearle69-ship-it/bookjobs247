# StressFree Service · Call Capturer

**StressFree Service** is the umbrella brand: a portfolio of low-cost apps that
do the admin for local service businesses. **Call Capturer** is the first
tool. One deployment serves both domains:

| URL | What |
|---|---|
| `stressfreeservicetools.com/` | Umbrella page: all tools, "coming soon" waitlists (signups in `/admin`). Any other path redirects to callcapturer.com |
| `callcapturer.com/` | Call Capturer sales page: agency comparison, ROI calculator, pricing, FAQ |
| `callcapturer.com/for/<trade>` | Per-trade pages (plumbers, electricians, hvac, roofers, locksmiths…) |
| `callcapturer.com/signup`, `/app` | The app (installable on the phone's home screen) |
| `callcapturer.com/admin`, `/admin/trades` | Your operator panel and the trade-script editor |
| `callcapturer.com/tools` | Preview of the umbrella page |

Names and domains are settings (`BRAND_NAME`, `APP_NAME`, `BRAND_URL`,
`PUBLIC_BASE_URL`), so renaming needs no code change. To add a future tool to
the umbrella page, add it to `app/products.py`.

## Call Capturer

An AI receptionist for local tradespeople. The owner forwards the calls they
miss to their Call Capturer number. When a call comes in, a voice agent answers
in their business's name and takes the caller's name, callback number,
address, the job and how urgent it is. The owner gets a push notification
and can see every call in a phone-friendly app. A one-tap **ON/OFF** switch
sends missed calls to a plain voicemail instead.

Self-serve: sign up → business details (trade, greeting name, assistant name,
voice) → pay (Stripe) → number assigned automatically → one-tap forwarding
codes → done.

| | US | UK |
|---|---|---|
| Price | $29/month | £25/month |
| Included | 60 answered minutes | 60 answered minutes |
| Overage | $0.25/min (metered) | £0.20/min (metered) |
| Number | Bought instantly (owner's area code if available) | 07 mobile number from your pre-bought pool |

Voicemail (when the assistant is OFF, or as a fallback) and calls under 20
seconds (robocalls, instant hang-ups) are never billed.

The Call Capturer number is **never seen by callers**: they dial the owner's
usual number, and the owner's phone forwards unanswered calls to it. It only
has to be in the same country as the owner's phone (forwarding abroad costs
the owner money).

### Built-in safeguards (to keep support low)
- **Caller ID problems:** if the network passes the owner's own number, or
  "anonymous", as the caller, the assistant is told to collect and read back a
  callback number.
- **Alerts survive restarts:** missed-call wrap-ups and emergency re-alerts
  are stored in the database and run by a background loop every 30 seconds.
- **Email backup:** every call is emailed if the owner has no push
  notifications set up, and emergencies are always emailed.
- **Forwarding never set up:** if a number gets no calls in its first 3 days,
  the owner is emailed the setup link once.
- **Cancellation:** the number stays connected for 7 days. Callers reach
  voicemail, and each call sends the owner a "You missed a call" email with a
  one-tap restart (same number, no setup) and the code to turn forwarding off.
  After 7 days the number is released.
- **Schema upgrades:** new columns are added automatically on deploy
  (`app/migrate.py`).

## How a call flows

```
Caller ─► owner's mobile (rings first) ─► not answered / busy / no signal
       ─► carrier forwards to the Call Capturer Twilio number
       ─► POST /twilio/voice
            ├─ assistant ON + subscription active:
            │     register call with Retell (business details as dynamic variables)
            │     ─► <Dial><Sip>sip:{call_id}@sip.retellai.com
            │     ─► Retell webhooks call_ended / call_analyzed ─► details saved,
            │        minutes sent to Stripe's meter, push notification sent
            └─ assistant OFF / payment failed / Retell unreachable:
                  voicemail (<Record> + transcription) ─► saved + push notification
```

Some details of the design:
- **Four shared Retell agents in total** (US/UK accent × female/male voice),
  not one per customer. Each call passes in that business's details, greeting
  and its **trade script** (questions + emergency rules, from `/admin/trades`)
  as Retell dynamic variables. Customers edit their details in Settings and the
  next call uses them; you edit a trade's script in `/admin/trades` and every
  customer in that trade gets it on their next call. Editing
  `app/agent_prompt.py` and running `scripts/setup_retell.py --update` changes
  the core script for everyone.
- **Emergency calls** (as judged against the trade's emergency rules) send a
  🚨 push that stays on screen and vibrates hard, re-sent at 5 and 15 minutes
  until the owner opens the call. No SMS, because of US A2P 10DLC registration.
- **No SIP trunk** is needed. Each call is registered with Retell's
  register-phone-call API and dialled over SIP, which is what lets the
  ON/OFF switch work per call.
- **The caller always reaches something.** If Retell can't be reached or the
  SIP dial fails, the call falls back to voicemail. If a caller hangs up
  without leaving a message, the owner still gets a "missed call" entry.
- **Forwarding is set up once** with conditional-forwarding codes (`**004*`
  on GSM networks, which covers all UK networks and AT&T/T-Mobile, or `*71`
  on Verizon). The owner's phone still rings first. The ON/OFF switch never
  needs the owner to dial anything.

## Go-live checklist

Accounts you need (all pay-as-you-go): **Railway** (hosting, ~$5–20/mo),
**Twilio** (numbers + call minutes), **Retell** (the AI voice), **Stripe**
(billing), **Postmark** (email, free tier to start), and your two domains:
**callcapturer.com** and **stressfreeservicetools.com**. Do everything in test mode first (step 8), then switch Stripe to live.

### 1. Domains + hosting (Railway)
1. (You already own both domains.)
2. Railway: New project → **Deploy from GitHub repo** → this repo (it builds
   from the `Dockerfile`; healthcheck `/healthz`). Pick the branch you deploy.
3. Add a **Postgres** service; on the app service set
   `DATABASE_URL=${{Postgres.DATABASE_URL}}`.
4. Settings → Networking → **Custom domain**: add `callcapturer.com`,
   `www.callcapturer.com`, `stressfreeservicetools.com` and
   `www.stressfreeservicetools.com` to the same service. Add the DNS records
   Railway shows for each at your registrar.
5. Set `PUBLIC_BASE_URL=https://callcapturer.com`,
   `BRAND_URL=https://stressfreeservicetools.com`, `SECRET_KEY` and
   `ADMIN_PASSWORD` (long random strings), `ADMIN_EMAIL`, and
   `SUPPORT_EMAIL=hello@callcapturer.com`.

Tables are created (and later upgraded) automatically on start.

### 2. Email (Postmark)
Create a server, verify `callcapturer.com` as a sender domain (DNS records), and
set `POSTMARK_API_TOKEN` and `EMAIL_FROM=hello@callcapturer.com`. Email carries
password resets, "number ready", backup call alerts and win-back emails, so
do this before taking customers.

### 3. Push notification keys
```bash
python scripts/generate_vapid_keys.py
```
Set `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT=mailto:hello@callcapturer.com`.
**Never change them later**, or every owner has to re-enable notifications.

### 4. Twilio
1. Upgrade the account from trial (add a card). Trial accounts can't buy
   numbers for customers.
2. Set `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`.
3. **Voice → Settings → Geo permissions**: allow the US and UK.
4. **US numbers need nothing else.** They're bought automatically when a
   customer pays (voice only, so no A2P/10DLC registration is needed).
5. **UK:** Phone Numbers → Regulatory Compliance → create a **Bundle** for
   *your* business (UK mobile, business end user, company documents and
   address). Approval takes 1–3 days. Then buy 5–10 UK **mobile** (07)
   numbers under it and add each one in `/admin` → UK number pool. You get
   an email if the pool runs out.

### 5. Retell
1. Set `RETELL_API_KEY`. It's used for API calls and to verify webhooks.
2. Pick four voices and create the agents:
   ```bash
   python scripts/setup_retell.py --list-voices
   python scripts/setup_retell.py --us-female <id> --us-male <id> --gb-female <id> --gb-male <id>
   ```
   Set the four printed `RETELL_AGENT_ID_*` values. Run this *after*
   `PUBLIC_BASE_URL` is set, because it stores the webhook URL on the agents.

### 6. Stripe
1. In **test mode**: `STRIPE_SECRET_KEY=sk_test_... python scripts/setup_stripe.py`
   and set the four printed `STRIPE_PRICE_*` values.
2. Developers → Webhooks → Add endpoint `https://callcapturer.com/webhooks/stripe`
   with events `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`. Set
   `STRIPE_WEBHOOK_SECRET`.
3. Settings → Billing → **Customer portal**: enable cancel + update payment
   method.

### 7. Run the setup scripts somewhere
The scripts in steps 3, 5 and 6 need the env vars. Easiest: Railway → app
service → **⋯ → Shell** (or `railway run python scripts/...` locally).

### 8. End-to-end test (Stripe test mode)
1. Sign up at `https://callcapturer.com/signup`, pay with card `4242 4242 4242 4242`.
2. On your own mobile, tap **Turn on forwarding** on the Setup page.
3. From another phone, ring your mobile and don't answer. The assistant
   should answer as your business and ask your trade's questions.
4. Check: the call appears in the app, you get a notification (add the app to
   your home screen first), and the minutes show on the Stripe meter.
5. Flip the switch OFF and call again: you should get voicemail.
6. Cancel from Settings → Manage billing. You should get the "plan ended"
   email, and a call should give the win-back email.

### 9. Go live
Re-run step 6 with your **live** Stripe key (new prices, new webhook secret),
swap those env vars, and you're open.

## Admin (`/admin`)
- Customers: subscription status, number, ON/OFF, calls/minutes (30 days),
  and whether forwarding is working (we have received at least one call).
- **Retry number** for anyone whose provisioning failed.
- UK number pool management.
- **Retry billing usage** if Stripe was unreachable when a call ended.

## Development
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env    # set at least SECRET_KEY
uvicorn app.main:app --reload
pytest
```
To receive real calls locally, expose the app with a tunnel (e.g. ngrok), set
`PUBLIC_BASE_URL` to the tunnel URL and point a Twilio number's voice webhook
at `<url>/twilio/voice`.

`scripts/make_icons.py` regenerates the app icons.

## Known limits / next steps
- The background-job loop runs inside the web process. Run **one** instance
  (Railway's default). Scaling to several needs a lock or a separate worker.
- iPhone push needs iOS 16.4+ and the app added to the home screen. Email
  covers owners who don't.
- `app/migrate.py` only adds columns. Renames or type changes need a real
  migration tool (Alembic).
- Customers can't turn forwarding off from the app (only their phone can).
  The cancellation emails tell them how.
