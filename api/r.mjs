// GET /r/<code> — an affiliate link landing.
//
// Rewritten here from /r/:code by vercel.json. This is the first serverless function on
// this site; everything else is static.
//
// What it deliberately does NOT do: attribute the visitor, or claim a one-time offer
// code. Both happen later, in the app, once an authenticated account is asking — see
// POST /api/referral in the kinsense-monorepo repo. Attributing at click time would credit bots and
// link previews, and claiming a code at click time would drain a pool bought in batches
// from App Store Connect. A crawler that hits this URL costs us one lookup and nothing
// else.
//
// So all this does is: check the code names a real, approved affiliate, remember it in a
// cookie, and send the visitor to the App Store.
//
// Env (set in the Vercel project, not here):
//   SUPABASE_URL                 https://yindkqtxilizeqjfuclg.supabase.co
//   SUPABASE_SERVICE_ROLE_KEY    server-side only; `affiliates` has no anon read policy
//   APP_STORE_URL                where to send someone without the app

const COOKIE_DAYS = 30;

export default async function handler(req, res) {
  const code = String(req.query.code ?? "").trim().toLowerCase();
  const appStore = process.env.APP_STORE_URL ?? "https://apps.apple.com/app/id6798410492";

  // A malformed code is not worth a round trip. Slugs are what we generate: lowercase,
  // alphanumeric, hyphens.
  if (!/^[a-z0-9-]{2,32}$/.test(code)) return res.redirect(302, "/");

  const affiliate = await lookupAffiliate(code);
  if (!affiliate) {
    // Unknown or unapproved. Send them to the site rather than explaining which codes
    // exist — an endpoint that distinguishes "no such affiliate" from "not approved yet"
    // is an enumeration oracle, and the visitor cannot act on the difference anyway.
    return res.redirect(302, "/");
  }

  // The cookie is a hint, not the record of truth. It survives the App Store round trip
  // on the same browser and is read back by the site if they return; the durable
  // attribution is written server-side when the app calls POST /api/referral. Lax
  // rather than Strict so it survives arriving from a link in another app.
  res.setHeader("Set-Cookie", [
    `ref=${encodeURIComponent(code)}`,
    "Path=/",
    `Max-Age=${COOKIE_DAYS * 24 * 60 * 60}`,
    "SameSite=Lax",
    "Secure",
    // Readable by the landing page so it can say who sent you. Nothing secret is in it.
  ].join("; "));

  res.setHeader("Content-Type", "text/html; charset=utf-8");
  // No-store: the response embeds one specific affiliate and sets their cookie, so a
  // shared cache serving it to the next visitor would misattribute them.
  res.setHeader("Cache-Control", "no-store");
  return res.status(200).send(page(affiliate.name ?? code, appStore));
}

/** The `affiliates` table has no anon read policy on purpose, so this reads with the
 *  service role. Approved only — a pending affiliate's link should behave as if it does
 *  not exist yet. */
async function lookupAffiliate(code) {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) {
    console.error("[r] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set");
    return null;
  }
  const q = `${url}/rest/v1/affiliates?select=code,status&code=eq.${encodeURIComponent(code)}&status=eq.approved&limit=1`;
  try {
    const r = await fetch(q, { headers: { apikey: key, Authorization: `Bearer ${key}` } });
    if (!r.ok) {
      console.error(`[r] affiliate lookup ${r.status}`);
      return null;
    }
    const rows = await r.json();
    return rows?.[0] ? { name: rows[0].code } : null;
  } catch (e) {
    console.error(`[r] affiliate lookup failed: ${e.message}`);
    return null;
  }
}

function page(who, appStore) {
  const safe = String(who).replace(/[<>&"]/g, (c) =>
    ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[c]));
  return `<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TribeSentry — invited by ${safe}</title>
<meta name="robots" content="noindex">
<link rel="stylesheet" href="/style.css">
</head><body>
<main class="wrap" style="max-width:38rem;padding:4rem 1.25rem">
  <h1>You were invited by ${safe}</h1>
  <p>Install TribeSentry and your discount is applied when you subscribe. Live location,
     SOS and crash detection are free either way.</p>
  <p><a class="cta" href="${appStore}">Get TribeSentry on the App Store</a></p>
  <p style="font-size:.85rem;opacity:.7">Open this link on the iPhone you'll use the app
     on — the invite is remembered in this browser.</p>
</main>
</body></html>`;
}
