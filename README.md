# Spine Automation – Flask website + admin portal

Public pages: **Home**, **Gallery** (grouped by category, with filter), **Project detail** (photo lightbox), **Contact / Request Quote**.
Admin portal at **/admin**: add/edit/delete projects, create categories on the fly, manage inquiries.

## Run locally

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py                     # http://127.0.0.1:5000
```

Admin: http://127.0.0.1:5000/admin  
Default login: `admin` / `ChangeMe@123` (**change before going live**, see below).

## Before going live – do these 3 things

1. **Real contact details.** Edit the `COMPANY` block at the top of `app.py`
   (phone, e-mail, address, hours, WhatsApp) or set env vars
   `COMPANY_PHONE`, `COMPANY_EMAIL`, `COMPANY_ADDRESS`, `COMPANY_HOURS`, `COMPANY_WHATSAPP`.
   Every "Call Now" button on the site uses the phone number as a `tel:` link.
2. **Admin password.** Set `ADMIN_PASSWORD` (and optionally `ADMIN_USERNAME`).
3. **HTTPS settings.** Behind HTTPS set `SECURE_COOKIES=1`; behind nginx / a hosting proxy set `TRUST_PROXY=1`.

Also edit `SERVICES` and `PROCESS` in `app.py` to match what you actually offer.

```bash
# example production start
export ADMIN_PASSWORD='a-long-unique-password'
export SECURE_COOKIES=1 TRUST_PROXY=1
gunicorn -w 2 -b 0.0.0.0:8000 app:app
```

## Where data lives (back these up!)

| What | Where |
|---|---|
| Projects, categories, inquiries | `instance/spine.db` (SQLite) |
| Uploaded photos | `uploads/` (served at `/media/…`) |
| Session secret | `instance/secret.key` (auto-created; or set `SECRET_KEY`) |

On hosts with ephemeral disks (Render/Heroku free tiers etc.) attach a persistent disk and point
`SPINE_INSTANCE_DIR` and `SPINE_UPLOAD_DIR` at it, otherwise uploads vanish on redeploy.

## Using the admin

* **Projects → Add project**: title, description, cover image, any number of gallery photos.
* **Category**: pick an existing one, or choose "Create new category…" and type a name – it is created instantly and the project appears under it on the live Gallery and Home page.
* **Edit** a project to change text/category, replace the cover, remove photos or add more.
* **Categories** page: rename, add, delete (only empty ones can be deleted).
* **Inquiries**: every quote-form submission is stored here with click-to-call / e-mail buttons; new ones show a badge.

## Notes

* Uploads accept JPG / PNG / WEBP / GIF only, are verified as real images, and (with Pillow) resized to max 1920 px.
* All forms are CSRF-protected; login is rate-limited; the contact form has a honeypot and rate limit.
* Contact form submissions are saved to the admin portal; they are **not** e-mailed. Add SMTP or a WhatsApp/Telegram hook in the `contact()` route if you want instant alerts.
* Headings use Google Fonts (Barlow Condensed + Inter) – needs internet on the visitor's side, falls back to system fonts otherwise.
