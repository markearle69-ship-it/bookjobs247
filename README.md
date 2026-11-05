# On The Tools · Call Keeper

**On The Tools** is the umbrella brand: one sales site listing a portfolio of
low-cost apps that do the admin for local service businesses. **Call Keeper**
is the first tool. Both names are settings (`BRAND_NAME`, `APP_NAME`,
`PRODUCT_SLUG`), so renaming needs no code change.

Site map (one deployment serves everything):

| Path | What |
|---|---|
| `/` | Umbrella home: all tools, "coming soon" waitlists (signups in `/admin`) |
| `/call-keeper` | Call Keeper sales page: agency comparison, ROI calculator, pricing, FAQ |
| `/call-keeper/for/<trade>` | Per-trade pages (plumbers, electricians, hvac, roofers, locksmiths…) |
| `/signup`, `/app` | The Call Keeper app (installable on the phone's home screen) |
| `/admin`, `/admin/trades` | Your operator panel and the trade-script editor |

To add a future tool to the home page, add it to `app/products.py`.

## Call Keeper

An AI receptionist for local tradespeople. The owner forwards the calls they
miss to their Call Keeper number. When a call comes in, a voice agent answers
in their business's name and takes the caller's name, callback number,
address, the job and how urgent it is. The owner gets a push notification
and can see every call in a phone-friendly app. A one-tap **ON/OFF** switch
sends missed calls to a plain voicemail instead.

Self-serve: sign up → business details (trade, greeting name, assistant name,
voice, US area code) → pay (Stripe) → number assigned automatically → one-tap
forwarding codes → done.

| | US | UK |
|---|---|---|
| Price | $29/month | £25/month |
| Included | 60 answered minutes | 60 answered minutes |
| Overage | $0.25/min (metered) | £0.20/min (metered) |
| Number | Local number in their area code, bought instantly | 07 mobile number from your pre-bought pool |

Voicemail (when the assistant is OFF, or as a fallback) is never billed.

## How a call flows

```
Caller ─► owner's mobile (rings first) ─► not answered / busy / no signal
       ─► carrier forwards to the Call Keeper Twilio number
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

### 1. Deploy to Railway
1. Create a Railway project, then **Deploy from GitHub repo** and pick this repo.
   It builds from the `Dockerfile` (healthcheck: `/healthz`).
2. Add a **Postgres** service. On the app service, set
   `DATABASE_URL=${{Postgres.DATABASE_URL}}`.
3. Generate a domain (or add your own), then set `PUBLIC_BASE_URL` to it.
4. Set `SECRET_KEY`, `ADMIN_PASSWORD` and `ADMIN_EMAIL` (see `.env.example`).

Tables are created automatically on first start.

### 2. Push notification keys
```bash
python scripts/generate_vapid_keys.py
```
Set `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` and `VAPID_SUBJECT`. **Never change
them later**, or every owner has to turn notifications on again.

### 3. Email (password resets, "your number is ready")
Set `POSTMARK_API_TOKEN` + `EMAIL_FROM` (or the SMTP settings).

### 4. Stripe
1. Run the setup script once in **test mode**, then again in live mode:
   ```bash
   STRIPE_SECRET_KEY=sk_test_... python scripts/setup_stripe.py
   ```
   It creates the meter (`agent_minutes`), the product, and a flat price plus
   a graduated metered price per currency, then prints the four
   `STRIPE_PRICE_*` values to set.
2. In Stripe go to **Developers → Webhooks → Add endpoint**:
   `https://<your-domain>/webhooks/stripe`, with these events:
   `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`.
   Set `STRIPE_WEBHOOK_SECRET` from it.
3. In **Settings → Billing → Customer portal**, turn on cancellation and
   payment-method updates. This is what "Manage payment, invoices or cancel"
   opens.

### 5. Retell
1. Set `RETELL_API_KEY`. It is used both for API calls and to verify webhook
   signatures.
2. Pick voices and create the four agents:
   ```bash
   python scripts/setup_retell.py --list-voices
   python scripts/setup_retell.py --us-female <id> --us-male <id> --gb-female <id> --gb-male <id>
   ```
   Set the four printed `RETELL_AGENT_ID_*` values. A missing male voice falls
   back to that country's female agent. The agents
   have their webhook (`/webhooks/retell`), post-call analysis fields and a
   10-minute call cap configured.
3. To change the script later, edit `app/agent_prompt.py`, then run
   `python scripts/setup_retell.py --update`.

### 6. Twilio
1. Set `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`. US numbers are bought
   automatically at signup and pointed at `/twilio/voice`.
2. **UK pool:** get a UK regulatory bundle approved for your own business,
   buy a handful of UK numbers under it, then add each one in `/admin`. The
   admin page warns when fewer than 3 are free, and you get an email if a
   signup finds the pool empty. Adding a number automatically serves anyone
   who was waiting.
3. Make sure your Twilio account has **Voice → Settings → Geo permissions**
   that allow the SIP dial to Retell. Twilio voice transcription (used for
   voicemails) is enabled by default.

### 7. End-to-end test (Stripe test mode)
Sign up at `/signup` with a test card (`4242 4242 4242 4242`), forward a phone to the
number, and call it from another phone without answering. Check that:
- the agent answers in your business's name
- the call appears in `/app` with the details, and you get a push notification
- the minutes appear in Stripe on the meter
- after you flip the switch OFF, you hear the voicemail greeting instead.

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
- Tables come from `create_all`. Add Alembic before making schema changes
  to a live database.
- The "missed call" follow-up timers run in-process, so a restart in the
  ~2 minutes after a call can skip one fallback notification. The call is
  still saved.
- iPhone push notifications need iOS 16.4+ and the app added to the home
  screen. The dashboard explains this when it detects an iPhone.
- Cancelled customers are reminded to turn off forwarding, but the app
  can't do it for them. US numbers are released when the subscription ends.
  UK pool numbers return to the pool after a 30-day cooldown.
