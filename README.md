# kinsense-public

Every public static page for the **TribeSentry** app. Deployed on **Vercel** (previously
GitHub Pages).

| Path | What it is |
|---|---|
| `index.html` | Marketing landing page, English — **generated** |
| `de/`, `es/`, `fr/`, `pt/`, `ru/`, `hi/`, `ar/`, `he/`, `ja/`, `zh/` | The same page in 10 more languages — **generated** |
| [`style.css`](style.css) | Shared stylesheet for the marketing pages |
| [`privacy.html`](privacy.html) | Privacy policy — also served at `/privacy` |
| [`auth-callback.html`](auth-callback.html) | Password-recovery / email-confirmation landing page |
| `sitemap.xml`, `robots.txt` | **Generated** |
| [`vercel.json`](vercel.json) | Routing + security headers |
| [`build/`](build) | Content source and generator (not deployed) |

Vercel serves the directory as-is — the generator runs locally and its output is
committed, so there is no build step or dependency on the hosting side.

## The marketing pages

All 11 language pages are generated from one content file, because they have to stay in
step and because `hreflang` only works if every page links to every other one. Both go
stale immediately if maintained by hand.

```bash
python3 build/generate.py   # rewrite the pages from build/content.py
python3 build/check.py      # markup, links, hreflang reciprocity, sitemap
```

**Edit [`build/content.py`](build/content.py), never the generated HTML** — it carries a
"do not edit" banner and is overwritten on the next run.

`check.py` reads the rewrites out of `vercel.json` when it resolves links, so it fails if
the routing config and the pages ever disagree. Run it before pushing.

The copy is derived from the Play Store listings in the app monorepo
(`store/listings/`), adapted for the web. If you change the pitch, change it in both —
they are separate files on purpose (store listings have field limits and policy
boilerplate that don't belong on a web page) but they should not contradict each other.

> The non-English copy has **not been reviewed by native speakers**. It reads correctly
> but idiom and keyword choice are exactly what a non-native writer gets wrong, and these
> pages are the SEO surface for those markets. Budget a native pass before promoting them.

## Routing and headers

`vercel.json` has to be plain JSON — Vercel validates it against a schema and rejects
unknown keys, including the `"//"` pseudo-comments that work in some other tools. So the
reasoning lives here instead.

**`cleanUrls` is off deliberately.** With it on, Vercel 308-redirects `/auth-callback.html`
to `/auth-callback` — and that exact URL is configured in Supabase as the Site URL and in
Redirect URLs. The redirect would have to be mirrored there or password recovery breaks.
Not worth it for cosmetics; `/privacy` gets an explicit rewrite instead.

**`frame-ancestors 'none'`** matters most on `auth-callback.html`: it stops the
password-reset form being framed by another site.

**`form-action` is `'self'`, not `'none'`.** That page's submit handler calls
`preventDefault()`, so no navigation should ever happen — but if the script fails to
attach, `'self'` degrades to a harmless page reload where `'none'` would be a blocked
submit with no feedback, and password reset is an App Store 5.1.1 dependency. `'self'`
still blocks posting the password to any other origin, which is the actual threat.

**The two `'unsafe-inline'`** are load-bearing: the pages use inline `<style>`, and
`auth-callback.html` is a single inline `<script>`.

**`connect-src` is pinned to the Supabase project** that the callback posts the new
password to. If the project ref in `auth-callback.html`'s `CFG` ever changes, change it
here too — miss it and recovery fails silently.

**`style.css` gets a one-hour cache**, not a long one: the filename carries no content
hash, so a long `max-age` would strand visitors on an old stylesheet after a deploy.

## Deploying

Connect the repo once in the Vercel dashboard — **Add New → Project → import
`yuvdror/kinsense-public`**. Framework preset **Other**, build command **empty**, output
directory **`.`**. After that every push to `main` deploys, and pull requests get preview
URLs. No CLI and no local credentials needed.

### Attaching the domain

In **Project → Settings → Domains**, add `tribesentry.cloud` (and `www` if you want it).
Vercel will show you the exact DNS records to create.

> **Do not move the nameservers to Vercel.** IONOS is both the DNS host and the mail
> host for `tribesentry.cloud`: the `mx00/mx01.ionos.com` records that receive mail,
> the root SPF authorizing IONOS to send, `_dmarc`, and the DKIM key. Outbound auth
> mail goes through IONOS SMTP, so those records are now load-bearing for *sending*
> as well as receiving. Switching nameservers drops all of them and silently breaks
> every password-reset and email-confirmation message the app sends — which is exactly
> the flow `auth-callback.html` exists to serve. Leave DNS where it is and add only
> the A/CNAME records Vercel asks for.
>
> (This warning previously named Resend's `send.` subdomain records. Those are being
> retired — see the migration order in the monorepo's DEPLOY.md — but the conclusion
> is unchanged and now applies to more records, not fewer.)

Serving the site at `tribesentry.cloud` keeps `auth-callback.html` on the URL it already
has, so **no Supabase configuration has to change**. That is the reason to use this domain
rather than a `*.vercel.app` one.

## After the first deploy

- [ ] **Turn GitHub Pages off** (repo → Settings → Pages → Source: None). Leaving it on
      means two live copies of the privacy policy that can drift apart.
- [ ] **Update the privacy policy URL** in Play Console (*Store listing → Privacy policy*)
      and App Store Connect (*App Privacy*). It has to change no matter what: the old URL
      was `yuvdror.github.io/kinsense-public/`, and on top of the host change the policy
      also moved off the site root to `/privacy`. Both consoles allow editing this field
      without a new review.
- [ ] **Check Supabase** — *Authentication → URL Configuration*. Site URL and Redirect
      URLs should both be `https://tribesentry.cloud/auth-callback.html`. Unchanged if you
      attached that domain; update them if you deployed to a `*.vercel.app` URL instead.
- [ ] **Test a real password reset** end to end. Trigger it from the app rather than
      opening the page directly — with no URL fragment the page correctly shows its
      "link has expired" state, so opening it by hand proves nothing.
- [ ] Point the hero call-to-action in `index.html` at the real Play listing once the app
      is live; it currently jumps to the pricing section (see the `TODO` comment).

## Privacy policy source of truth

The canonical text lives in the private app repo at `PRIVACY.md`. `privacy.html` here is
the rendered public version — update it there, then regenerate this page. Filled-in
values: developer **smart-apps**, contact **info@tribesentry.cloud**, effective
**July 26, 2026**, location-history retention **7 days**, minimum age **13**.

The 7-day pruning the policy promises **is** enforced, by the nightly `pg_cron` job in
migration `20260726000001`.

Still outstanding: have the policy reviewed for the relevant jurisdictions (Israel +
EEA/UK for GDPR, California for CCPA).

## A note on `auth-callback.html`

It used to live in the app monorepo at `web/auth-callback.html`; it moved here so that all
public static content deploys from one place. It embeds the Supabase project URL and the
**publishable** key — both public by design, the same pair ships inside both mobile apps.
The recovery token arrives in the URL *fragment*, which browsers never send to a server,
so the host never sees it.

If the project ref or publishable key ever change, update them in **two** places: the
`CFG` object near the bottom of that file, and the `connect-src` directive in
[`vercel.json`](vercel.json). Miss the second and password recovery fails silently.
