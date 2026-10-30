# -*- coding: utf-8 -*-
"""report.py - Dashboard HTML (single page; data loaded from /api/dashboard)"""

PAGE = """<!DOCTYPE html>
<html lang="en" translate="no" class="notranslate">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- Block browser auto-translation. In a Korean locale, if Edge/Chrome translates
     the whole page the menu names change and confuse the user. -->
<meta name="google" content="notranslate">
<title>OrderFlow</title>
<style>
  :root {
    --bg:#f8fafc; --card:#ffffff; --border:#e2e8f0; --text:#0f172a;
    --muted:#64748b; --accent:#2563eb; --accent-soft:#eff6ff;
    --danger:#dc2626; --danger-soft:#fef2f2; --green:#16a34a;
    --green-soft:#f0fdf4; --amber:#d97706; --amber-soft:#fffbeb;
    --violet:#7c3aed; --violet-soft:#f5f3ff; --radius:12px;
    /* Floating island sidebar (dark blue gradient). Three stops instead of two so
       the ramp stays deep at the top where the brand sits and only reaches a
       readable mid-blue at the bottom; every text token below is contrast-checked
       against BOTH ends of that ramp, not just the average. */
    --isl-1:#0a1428; --isl-2:#10233f; --isl-3:#1b3a6b;
    --isl-text:#eaf1ff; --isl-muted:#a9bcd8; --isl-dim:#8ea6c9;
    --isl-accent:#7cb0ff; --isl-line:rgba(255,255,255,.10);
    --isl-gut:16px;      /* page inset around the island - also used by JS */
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
    font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Inter,
    "Helvetica Neue",Arial,sans-serif;
    -webkit-font-smoothing:antialiased; }
  /* ── Floating island sidebar ──────────────────────────────────────────────
     The menu is detached from the window edges: the page keeps a gutter, the
     island carries its own radius + elevation, and it is sticky with its own
     scroll so Settings / Sync stay reachable while a long table scrolls.
     Everything below is scoped with `.sidebar` so the light content area is
     untouched - the app keeps one light theme, the menu is a dark accent. */
  .layout { display:flex; min-height:100vh; gap:var(--isl-gut);
    padding:var(--isl-gut); align-items:flex-start; }

  /* ── A rail, not a column (2026-10-25, click to open since 2026-10-28) ──
     Collapsed the menu is 62px of icons. CLICKING the plate - or pressing
     Enter / Space on it - expands it to the full list OVER the page. It used
     to open on hover, which is pleasant with a mouse and hostile to everyone
     else: the plate opened while the pointer crossed it on the way to a table,
     and a keyboard user never got it at all. The width lives on `.sidebar`
     while the space that is RESERVED lives on `.sidewrap`, so expanding never
     reflows the table behind it: a menu that resizes the page under the
     pointer is the one thing a hover-expand rail must not do.
     The curve is ease-out (cubic-bezier(.16,1,.3,1)) because the eye reads the
     end of a movement: the plate arrives quickly and settles, and the labels
     fade in 110ms later so they ride the edge instead of appearing on top of
     an already-finished animation. */
  .sidewrap { flex:0 0 62px; width:62px; align-self:flex-start;
    height:calc(100vh - (var(--isl-gut) * 2));
    position:sticky; top:var(--isl-gut); z-index:60; }
  .sidebar { width:62px; height:100%;
    overflow-y:auto; overflow-x:hidden;
    padding:14px 10px 12px; display:flex; flex-direction:column;
    border-radius:20px; border:1px solid rgba(255,255,255,.08);
    background:
      radial-gradient(115% 60% at 6% -4%, rgba(96,165,250,.30),
        rgba(96,165,250,0) 62%),
      linear-gradient(168deg, var(--isl-1) 0%, var(--isl-2) 46%,
        var(--isl-3) 100%);
    box-shadow:0 22px 44px -16px rgba(8,20,45,.55),
      0 4px 12px rgba(8,20,45,.26), inset 0 1px 0 rgba(255,255,255,.09);
    transition:width .30s cubic-bezier(.16,1,.3,1),
      padding .30s cubic-bezier(.16,1,.3,1),
      box-shadow .30s cubic-bezier(.16,1,.3,1);
    scrollbar-width:thin; scrollbar-color:rgba(255,255,255,.22) transparent; }
  .sidebar.open { width:238px; padding:16px 14px 14px;
    box-shadow:0 28px 62px -18px rgba(8,20,45,.64),
      0 6px 16px rgba(8,20,45,.30), inset 0 1px 0 rgba(255,255,255,.11); }
  .sidebar::-webkit-scrollbar { width:8px; }
  .sidebar::-webkit-scrollbar-track { background:transparent; }
  .sidebar::-webkit-scrollbar-thumb { background:rgba(255,255,255,.18);
    border-radius:99px; }
  .sidebar::-webkit-scrollbar-thumb:hover { background:rgba(255,255,255,.30); }

  /* Brand + section labels. The monogram is what the 62px rail can hold, so
     the wordmark is hidden until the plate expands - swapping the two instead
     of scaling one keeps both crisp. */
  .sidebar .brand { color:var(--isl-text); padding:0 0 10px; min-height:40px;
    /* It is the OPEN CONTROL now, so it is a real <button>: reset the UA's
       button chrome and say so with a pointer, or the only way to find the
       toggle is to read the title. */
    display:block; width:100%; border:0; background:transparent;
    font:inherit; text-align:left; cursor:pointer; }
  .sidebar .brand:hover .blogo { background:rgba(96,165,250,.30);
    border-color:rgba(147,197,253,.45); }
  .sidebar .blogo { display:flex; align-items:center; justify-content:center;
    width:36px; height:36px; margin:0 auto; border-radius:10px;
    font-size:12px; font-weight:800; letter-spacing:.04em;
    color:#dbeafe; background:rgba(96,165,250,.20);
    border:1px solid rgba(147,197,253,.30); }
  .sidebar .bfull { display:none; padding:0 8px; }
  .sidebar.open .blogo { display:none; }
  .sidebar.open .bfull { display:block; }
  .sidebar .brand span { color:var(--isl-accent); }
  .sidebar .brandsub { color:var(--isl-muted); }
  .sidebar .buildtag { background:rgba(255,255,255,.10);
    color:var(--isl-muted); }
  /* Collapsed, a section label is a 1px rule: it still separates the four
     blocks of the menu without needing a word to fit in 40px. */
  .sidebar .navsec { color:var(--isl-dim); padding:4px 12px 2px;
    margin-top:11px; padding-top:11px; border-top-color:var(--isl-line);
    white-space:nowrap; overflow:hidden;
    transition:opacity .16s ease, color .16s ease; }
  .sidebar .navdiv { border-top-color:var(--isl-line); }
  .sidebar:not(.open) .navsec {
    color:transparent; margin:9px 8px; padding:0; height:1px;
    background:var(--isl-line); border-top:none; }

  /* Nav rows. Icons are lucide, drawn as inline SVG so the rail has no network
     dependency and the stroke inherits currentColor (which is what lets the
     active row tint its own icon). */
  .sidebar .navbtn { color:#c6d5ec; position:relative; justify-content:flex-start;
    gap:11px; padding:10px 11px; font-size:14px; font-weight:600;
    transition:background .14s ease, color .14s ease; }
  .sidebar .nic { width:20px; height:20px; flex-shrink:0; display:inline-flex;
    align-items:center; justify-content:center; }
  .sidebar .nic svg { width:19px; height:19px; display:block; }
  .sidebar:not(.open) .navbtn { justify-content:center;
    padding:10px 0; gap:0; }
  /* Railed, the label keeps its place in the DOM (that is what lets it fade in
     on hover) but must not keep its place in the FLEX LINE: a centred row
     measures icon + gap + label, so leaving the label in the line pushed every
     icon half a label-width off centre - and not by the same amount per row,
     because "Customer Master" is wider than "Inbox". Absolutely positioned,
     the icon alone decides where the row centres. */
  .sidebar:not(.open) .navbtn .nlb {
    position:absolute; left:46px; top:50%; pointer-events:none;
    transform:translateY(-50%) translateX(-4px); }
  .sidebar:not(.open) .navbtn .badge {
    position:absolute; top:6px; right:8px; margin:0; }
  /* A "0" pill in a 62px rail is noise next to a count that says nothing. */
  .sidebar:not(.open) .navbtn .badge.zero { opacity:0; }
  .sidebar .nlb { white-space:nowrap; overflow:hidden; opacity:0;
    transform:translateX(-4px); pointer-events:none;
    transition:opacity .13s ease, transform .13s ease; }
  .sidebar.open .nlb { opacity:1; transform:none;
    transition-delay:.11s; }
  .sidebar .navbtn:hover { background:rgba(255,255,255,.08); color:#fff; }
  .sidebar .navbtn.active { color:#fff;
    background:linear-gradient(90deg, rgba(96,165,250,.32),
      rgba(96,165,250,.08)); }
  .sidebar .navbtn.active::before { content:""; position:absolute;
    left:-9px; top:50%; transform:translateY(-50%); width:3px; height:20px;
    border-radius:3px; background:var(--isl-accent); }
  .sidebar:not(.open) .navbtn.active::before {
    left:-10px; }

  .sidebar .badge { background:rgba(147,197,253,.16); color:#cfe0ff;
    border:1px solid rgba(147,197,253,.22); margin-left:auto; }
  .sidebar .navbtn.active .badge { background:#2563eb; border-color:#3b82f6;
    color:#fff; }
  /* A number needs ~20px of text; the rail has none to spare, so the badge
     degrades to a dot that says "there is something here" and nothing more. */
  .sidebar:not(.open) .navbtn .badge:not(.zero) {
    position:absolute; top:7px; right:7px; margin:0;
    width:7px; height:7px; min-width:0; padding:0; font-size:0;
    border:none; border-radius:50%; background:var(--isl-accent); }
  .sidebar:not(.open) .navbtn.active .badge:not(.zero) {
    background:#93c5fd; }

  /* The footer (sync state + the reset control) is the only multi-line block in
     the menu, so it cannot be squeezed into 42px - it folds away while railed
     instead of being cropped, which also keeps the rows ABOVE it from moving
     when the plate expands. Both live in here because a reset button reachable
     as a bare icon would be a destructive action one stray click away. */
  .railfoot { overflow:hidden; max-height:320px; opacity:1;
    transition:max-height .26s cubic-bezier(.16,1,.3,1), opacity .16s ease; }
  .sidebar .syncbox { overflow:hidden; }
  .sidebar .rstrow { display:flex; align-items:center; gap:9px; width:100%;
    padding:8px 11px; margin-top:2px; border:none; background:transparent;
    color:#fca5a5; font-family:inherit; font-size:12.5px; font-weight:600;
    border-radius:8px; cursor:pointer; text-align:left; }
  .sidebar .rstrow:hover { background:rgba(248,113,113,.15); color:#fecaca; }
  .sidebar .rstrow svg { width:16px; height:16px; flex-shrink:0; }
  .sidebar:not(.open) .railfoot { max-height:0;
    opacity:0; }
  .sidebar .syncrow { color:var(--isl-text); }
  .sidebar .syncline { color:#b9c9e2; }
  .sidebar .syncline.muted { color:var(--isl-dim); }
  .sidebar .syncline.err { color:#ffaaaa; }
  .sidebar .btn { background:rgba(255,255,255,.09); color:var(--isl-text);
    border-color:rgba(255,255,255,.16); }
  .sidebar .btn:hover { background:rgba(255,255,255,.16); }
  .sidebar .btn[disabled] { opacity:.55; cursor:default; }
  .sidebar .dot.blue { background:var(--isl-accent); }
  .sidebar .dot.green { background:#4ade80; }
  .sidebar .dot.red { background:#f87171; }
  .sidebar .dot.yellow { background:#fbbf24; }
  .sidebar .dot.gray { background:#94a3b8; }

  /* Keyboard focus must stay visible on a dark plate (default ring is not) */
  .sidebar .navbtn:focus-visible, .sidebar .btn:focus-visible,
  .sidebar .rstrow:focus-visible {
    outline:2px solid #93c5fd; outline-offset:-2px; }

  @media (prefers-reduced-motion:reduce) {
    .sidebar, .sidebar .navbtn, .sidebar .nlb, .sidebar .navsec,
    .sidebar .railfoot, .sidebar .btn { transition:none; }
  }

  .navspacer { margin-top:auto; }
  /* Fold the whole menu away on narrow screens to free up table space */
  .layout.railed .sidewrap { display:none; }
  .railbtn { width:34px; height:34px; flex-shrink:0; border-radius:8px;
    border:1px solid var(--border); background:var(--card); cursor:pointer;
    font-size:15px; color:var(--muted); line-height:1; }
  .railbtn:hover { background:var(--bg); color:var(--text); }
  /* Sticky table header - keep column names visible in long lists */
  .cardbody { position:relative; }
  table thead th, table tr:first-child th { position:sticky; top:0; z-index:2; }
  .brand { font-size:20px; font-weight:700; padding:4px 10px 16px;
    letter-spacing:-0.02em; }
  .brandsub { font-size:11px; font-weight:600; color:#94a3b8;
    letter-spacing:.06em; text-transform:uppercase; margin-top:2px; }
  .brand span { color:var(--accent); }
  /* Material Codes tree */
  .tnode { display:flex; align-items:center; gap:8px; padding:8px 10px;
    background:var(--card); border:1px solid var(--border);
    border-radius:8px; margin-bottom:6px; cursor:pointer;
    transition:border-color .12s; }
  .tnode:hover { border-color:#cbd5e1; }
  .tcar { font-style:normal; color:var(--muted); font-size:12px; width:12px; }
  .tname { font-weight:600; font-size:13.5px; }
  .tname2 { font-weight:600; font-size:12.5px; color:#475569; }
  .tcount { font-size:11.5px; color:var(--muted); }
  .tbranch { margin:0 0 10px 16px; padding-left:14px;
    border-left:2px solid var(--border); }
  .tsub { display:flex; align-items:center; gap:8px; padding:6px 0 2px; }
  .ttype2 { display:flex; align-items:center; gap:7px; padding:4px 0 2px 14px; }
  .t2chip { font-size:11px; font-weight:600; padding:1px 8px;
    border-radius:999px; background:var(--accent-soft); color:var(--accent); }
  .cgrid { display:grid; gap:4px; padding:3px 0 8px;
    grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); }
  .cgrid.deep { padding-left:14px; }
  .ccode { position:relative; font-size:11.5px; font-family:Consolas,
    'Courier New',monospace; padding:4px 8px; background:var(--card);
    border:1px solid var(--border); border-radius:5px;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .ccode:hover { border-color:#cbd5e1; }
  .cdel { display:none; position:absolute; right:3px; top:50%;
    transform:translateY(-50%); font-style:normal; font-size:10px;
    color:var(--danger); background:var(--card); padding:2px 4px;
    cursor:pointer; border-radius:3px; }
  .ccode:hover .cdel { display:inline; }
  .buildtag { display:inline-block; margin-left:6px; padding:1px 6px;
    background:#f1f5f9; border-radius:4px; color:#94a3b8; font-size:10px;
    font-weight:600; letter-spacing:0; }
  .navbtn { display:flex; align-items:center; justify-content:space-between;
    width:100%; padding:12px 12px; margin-bottom:3px; border:none;
    background:transparent; color:#334155; font-size:15.5px; font-weight:600;
    border-radius:8px; cursor:pointer; text-align:left; font-family:inherit;
    transition:background .1s ease; }
  .navbtn:hover { background:#f1f5f9; color:var(--text); }
  .navbtn.active { background:var(--accent-soft); color:var(--accent); }
  .badge { background:var(--accent-soft); color:var(--accent);
    border-radius:999px; padding:1px 8px; font-size:11px; font-weight:700;
    min-width:20px; text-align:center; }
  .navbtn.active .badge { background:#dbeafe; }
  .badge.zero { display:none; }
  .navdiv { border-top:1px solid var(--border); margin:10px 4px; }
  .syncbox { padding:8px 12px 12px; }
  .syncrow { display:flex; align-items:center; gap:7px; font-size:13px;
    margin-bottom:6px; }
  .syncline { font-size:12px; color:#475569; line-height:1.7; }
  .syncline.muted { color:#94a3b8; }
  .syncbtn { width:100%; margin-top:9px; padding:7px; font-size:12.5px; }
  .navsec { font-size:11px; font-weight:700; color:#94a3b8;
    text-transform:uppercase; letter-spacing:.07em; padding:6px 12px;
    margin-top:16px; border-top:1px solid var(--border); padding-top:14px; }
  .gearbtn { width:36px; height:36px; border-radius:50%; border:1px solid
    var(--border); background:var(--card); cursor:pointer; font-size:17px;
    color:var(--muted); display:inline-flex; align-items:center;
    justify-content:center; transition:all .12s ease; }
  .gearbtn:hover { color:var(--text); background:var(--bg); }
  .gearbtn.active { background:var(--accent-soft); color:var(--accent);
    border-color:#bfdbfe; }
  .setbody { padding:18px 20px; }
  .setcard { max-width:720px; }
  /* Option cards */
  .opt { display:flex; gap:10px; align-items:flex-start; padding:12px 14px;
    border:1px solid var(--border); border-radius:10px; margin-bottom:8px;
    cursor:pointer; background:#fff; transition:border-color .12s; }
  .opt:hover { border-color:#cbd5e1; }
  .opt.on { border-color:var(--accent); background:var(--accent-soft); }
  .opt input { accent-color:var(--accent); margin-top:2px; flex-shrink:0; }
  .opt .muted { font-size:12.5px; }
  /* Input area dependent on the selected option */
  .subfields { margin:4px 0 4px 14px; padding:10px 0 4px 18px;
    border-left:2px solid var(--border); }
  .subfields.off { opacity:.45; pointer-events:none; }
  .frow { display:grid; grid-template-columns:110px 1fr; gap:14px;
    align-items:start; margin-bottom:14px; }
  .frow > label { font-size:13px; font-weight:600; color:var(--text);
    padding-top:7px; }
  .fctl { min-width:0; }
  .fctl input[type=text], .fctl select { width:100%; max-width:340px; }
  .fctl input.short { width:80px; }
  .inline { display:flex; gap:8px; align-items:center; flex-wrap:wrap;
    margin-bottom:6px; }
  .inline select { max-width:250px; }
  .fhint { font-size:12px; color:var(--muted); margin-top:2px; }
  /* ── The file picker (Data screens) ─────────────────────────────────────
     Replaces the browser's own "Choose File" control, which cannot be styled
     and reads as a form leftover next to the rest of the page. Three layers -
     back, page, front - so the hover can lift the sheet and tip the cover; the
     palette is the app's blue with the amber folder the Quick Convert drop
     target already uses, so the two "give me a file" affordances match. */
  .docpick { display:inline-flex; align-items:center; gap:10px;
    flex-wrap:wrap; }
  .docbtn { display:flex; align-items:center; justify-content:flex-start;
    gap:10px; height:44px; max-width:330px; padding:0 15px;
    border:none; border-radius:9px; cursor:pointer;
    background:linear-gradient(320deg, #034d92, #003cff);
    box-shadow:0 8px 16px rgba(0,60,255,.18);
    transition:background .3s, box-shadow .3s, transform .12s; }
  .docbtn:hover { background:linear-gradient(320deg, #0a58a6, #1f5bff);
    box-shadow:0 12px 22px rgba(0,60,255,.28); }
  .docbtn:active { transform:scale(.95); }
  .docbtn:focus-visible { outline:none;
    box-shadow:0 0 0 3px rgba(37,99,235,.35); }
  .folderContainer { position:relative; flex:0 0 auto; width:30px; height:26px;
    perspective:600px; }
  .folderContainer svg { display:block; }
  .fileBack { position:absolute; left:50%; bottom:0; width:30px;
    transform:translateX(-50%); }
  .filePage { position:absolute; left:50%; bottom:5px; width:16px;
    transform:translateX(-50%);
    transition:transform .3s ease-out; }
  .fileFront { position:absolute; left:50%; bottom:0; width:29px;
    transform:translateX(-50%); transform-origin:bottom;
    transition:transform .3s ease-out; }
  /* The -50% is repeated in every hover transform: dropping it would snap the
     layer to the left instead of lifting it. */
  .docbtn:hover .filePage { transform:translate(-50%, -5px); }
  .docbtn:hover .fileFront { transform:translateX(-50%) rotateX(28deg); }
  .doctext { font-size:12.5px; font-weight:600; letter-spacing:.3px;
    color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    max-width:250px; }
  .doctext.has { font-weight:500; color:#dbeafe; }
  .docpick .docname { font-size:12px; color:var(--muted); }
  .setactions { display:flex; gap:8px; align-items:center; margin-top:18px;
    padding-top:16px; border-top:1px solid var(--border); flex-wrap:wrap; }
  .setactions .spacer { flex:1; }
  .setfield { margin-top:14px; }
  .setfield label { display:block; font-size:12px; font-weight:600;
    color:var(--muted); margin-bottom:5px; }
  .setfield input { width:100%; max-width:420px; }
  .otest { margin-top:16px; padding:14px 16px; border-radius:10px;
    border:1px solid var(--border); background:var(--bg); font-size:13px; }
  .otest.good { background:var(--green-soft); border-color:#bbf7d0; }
  .otest.bad { background:var(--danger-soft); border-color:#fecaca; }
  .otbl { margin-top:8px; background:transparent; }
  .otbl td { border:none; padding:3px 10px 3px 0; vertical-align:top; }
  .otbl td:first-child { color:var(--muted); white-space:nowrap;
    width:150px; }
  .kpirow { display:grid; grid-template-columns:repeat(auto-fit,
    minmax(160px, 1fr)); gap:12px; margin-bottom:20px; }
  .kpi { background:var(--card); border:1px solid var(--border);
    border-radius:var(--radius); padding:16px 18px;
    box-shadow:0 1px 2px rgba(15,23,42,.04); }
  .kpi .val { font-size:24px; font-weight:700; letter-spacing:-0.02em; }
  .kpi .lbl { font-size:12px; color:var(--muted); margin-top:2px; }

  /* The content column used to stop growing at 1400px, so maximising the
     window on a wide screen produced no extra room for the table - it stayed
     at 1400 - 64 of padding while the table itself demanded 1290+. Two fixes:
     no max-width, and `min-width:0`, which is the one that matters - a flex
     item defaults to min-width:auto, so a wide child (that table) forces the
     ITEM to be at least as wide as its content and pushes the whole layout
     past the viewport, giving the page a horizontal scrollbar no matter how
     wide the window is. */
  .main { flex:1 1 auto; min-width:0; padding:28px 32px; }
  .pagehead { display:flex; align-items:baseline; justify-content:space-between;
    margin-bottom:20px; }
  .pagehead h1 { font-size:22px; font-weight:700; margin:0;
    letter-spacing:-0.02em; }
  .meta { color:var(--muted); font-size:12.5px; }

  /* ── "API not connected" badge ────────────────────────────────────────────
     The one failure that looks like a product bug: with no API key every PO
     comes back with ZERO material codes and nothing raises. So it gets a badge
     in the corner of the screens that read POs, and the reason on hover.
     Hover OR keyboard focus opens the note, so it is reachable without a mouse. */
  .apiwarn { position:relative; display:inline-flex; align-items:center; gap:7px;
    font-size:12px; font-weight:600; color:#92400e; background:#fffbeb;
    border:1px solid #fcd34d; border-radius:999px; padding:4px 11px 4px 5px;
    cursor:pointer; white-space:nowrap; user-select:none; }
  .apiwarn:hover, .apiwarn:focus { background:#fef3c7; outline:none; }
  .apiwarn .aw-ico { width:17px; height:17px; border-radius:50%; flex-shrink:0;
    background:#f59e0b; color:#fff; font-size:11px; font-weight:800;
    display:inline-flex; align-items:center; justify-content:center; }
  .apiwarn .aw-tip { display:none; position:absolute; right:0;
    top:calc(100% + 9px); z-index:70; width:340px; padding:12px 14px;
    background:#fff; border:1px solid var(--border);
    border-left:3px solid #f59e0b; border-radius:9px;
    box-shadow:0 10px 30px rgba(15,23,42,.16);
    font-size:12px; font-weight:400; color:var(--text); line-height:1.5;
    white-space:normal; text-align:left; }
  .apiwarn:hover .aw-tip, .apiwarn:focus .aw-tip { display:block; }
  .apiwarn .aw-tip b { display:block; font-size:12.5px; margin-bottom:5px; }
  .apiwarn .aw-why { display:block; color:#b45309; margin-bottom:7px; }
  .apiwarn .aw-how { display:block; color:var(--muted); }
  .apiwarn .aw-link { display:block; margin-top:8px; color:var(--accent);
    font-weight:600; }
  .apiwarn .aw-link:hover { text-decoration:underline; }

  .card { background:var(--card); border:1px solid var(--border);
    border-radius:var(--radius); margin-bottom:20px; overflow:hidden;
    box-shadow:0 1px 2px rgba(15,23,42,.04); }
  /* A card that carries a split button must NOT clip: its menu is an absolute
     panel that drops BELOW the button, and .card's overflow:hidden cuts it off
     at the card's edge - for the export menus, which sit at the very bottom of
     their card, the panel vanished completely. :has() catches every such card
     (the two Master-Data export cards and Quick Convert's) without touching the
     call sites, and leaves the clipping that rounds table corners everywhere
     else intact. */
  .card:has(.split) { overflow:visible; }
  .card.ov { overflow:visible; }
  /* row-gap only bites when the head wraps (narrow window), so the normal
     layout is unchanged; flex-wrap keeps a crowded head inside its card. */
  .cardhead { display:flex; align-items:center; justify-content:space-between;
    padding:14px 18px; border-bottom:1px solid var(--border);
    flex-wrap:wrap; row-gap:8px; column-gap:12px; }
  .cardhead h3 { margin:0; font-size:15px; font-weight:600; }
  .cardhead .count { color:var(--muted); font-size:13px; }
  .cardbody { padding:0; }
  .cardnote { padding:12px 18px; color:var(--muted); font-size:13px;
    border-bottom:1px solid var(--border); background:#fcfdfe; }

  table { border-collapse:collapse; width:100%; font-size:13.5px; }
  th:last-child, td:last-child { padding-left:8px; padding-right:8px; }
  table.fixed th:first-child, table.fixed td:first-child {
    padding-left:8px; padding-right:8px; text-align:center; }
  th { text-align:left; padding:10px 14px; color:var(--muted); font-size:11.5px;
    font-weight:600; text-transform:uppercase; letter-spacing:.05em;
    border-bottom:1px solid var(--border); background:#fcfdfe;
    white-space:nowrap; }
  td { padding:9px 14px; border-bottom:1px solid #f1f5f9; vertical-align:middle; }
  tr:last-child td { border-bottom:none; }
  tr:hover td { background:#f8fafc; }
  tr.warnrow td { background:var(--amber-soft); }
  /* A line whose code is not in the Material Code list. Amber, not red: the
     line is not wrong, it is unconfirmed - and it is held back from the file
     until somebody ticks it, so the colour is a prompt, not an alarm. */
  tr.needrow td { background:var(--amber-soft); }
  tr.needrow td:first-child { box-shadow:inset 3px 0 0 var(--amber); }
  /* A unique suffix repair is safe enough to include automatically, but it is
     still a data correction and therefore remains conspicuously reviewable. */
  tr.fixrow td { background:var(--amber-soft); }
  tr.fixrow td:first-child { box-shadow:inset 3px 0 0 var(--amber); }
  .needpill { display:inline-block; margin-left:6px; padding:1px 7px;
    border-radius:999px; font-size:10.5px; font-weight:700;
    background:#fef3c7; color:#92400e; white-space:nowrap; }
  td.num, th.num { text-align:right; }

  .pill { display:inline-block; padding:2px 10px; border-radius:999px;
    font-size:12px; font-weight:600; }
  .pill.done { background:var(--green-soft); color:var(--green); }
  .st { display:inline-flex; align-items:center; gap:7px; font-weight:600;
    font-size:12.5px; white-space:nowrap; }
  .dot { width:9px; height:9px; border-radius:50%; display:inline-block; }
  .dot.blue { background:var(--accent); }
  .dot.green { background:var(--green); }
  .dot.red { background:var(--danger); }
  .dot.yellow { background:#eab308; }
  .dot.gray { background:#94a3b8; }
  .help { display:inline-flex; align-items:center; justify-content:center;
    width:15px; height:15px; border-radius:50%; background:#e2e8f0;
    color:var(--muted); font-size:10px; font-weight:700; cursor:help;
    position:relative; vertical-align:middle; margin-left:2px; }
  .help .helptip { display:none; position:absolute; top:20px; left:-8px;
    z-index:50; background:var(--card); border:1px solid var(--border);
    border-radius:10px; box-shadow:0 8px 24px rgba(15,23,42,.12);
    padding:12px 14px; width:300px; text-align:left; line-height:2;
    font-weight:400; text-transform:none; letter-spacing:0;
    font-size:12.5px; color:var(--text); }
  .help:hover .helptip { display:block; }
  /* Fixed layout so the colgroup widths are obeyed. The columns are PERCENTAGES
     summing to 100, so the table scales as a whole and no single column can
     absorb the surplus - see poTable() for why the subject column used to do
     exactly that. This floor is what keeps the editable Ship-To inputs usable on
     a narrow window; below it the cardbody scrolls, which is better than
     squashing them to nothing. */
  table.fixed { table-layout:fixed; min-width:1198px; }
  .cardbody { overflow-x:auto; }
  table.fixed select { width:100%; max-width:none; }
  .ell { overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
    max-width:100%; }
  table.fixed td { overflow:hidden; }
  td .ell { display:block; }
  .actions { display:inline-flex; gap:6px; }
  /* Completed rows (2026-10-27). The ERP column holds "Mark uploaded" plus
     "Undo" in ~115px: on one line they ran into the cell edge and the row read
     as broken, so they wrap instead. The uploaded-file column holds up to TWO
     names (full + simple), so each is its own flex line: the version chip
     keeps its width and the name ellipsises. */
  .erpacts { display:flex; flex-wrap:wrap; align-items:center; gap:4px 6px; }
  .erpf { display:flex; align-items:center; gap:6px; min-width:0; }
  .erpf .fmtchip { flex:0 0 auto; margin-right:0; }
  .erpf .attlink { min-width:0; overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap; }

  /* ── Row actions: Extract (blue) / Discard (red) ──────────────────────────
     The "3D key" look from the Tailwind snippet the desk sent - a thick bottom
     border as the key's side, brightness on hover, and the button physically
     pressing down on :active. Rebuilt in plain CSS because this page has no
     Tailwind build step.
     The padding is smaller than px-6 / py-2: that snippet is a page-level
     button, and two of them in a table row at 24px horizontal padding would
     have made every row ~3 lines tall and pushed the table past the viewport
     again. The proportions (radius, border, lift) are unchanged. */
  .tbtn { border:none; border-bottom:4px solid; border-radius:9px;
    padding:6px 11px; font-family:inherit; font-size:12px; font-weight:700;
    letter-spacing:.01em; color:#fff; cursor:pointer; white-space:nowrap;
    transition:filter .12s, transform .12s, border-bottom-width .12s;
    line-height:1.15; }
  .tbtn.blue { background:#3b82f6; border-bottom-color:#2563eb; }
  .tbtn.red  { background:#ef4444; border-bottom-color:#dc2626; }
  .tbtn:hover { filter:brightness(1.1); transform:translateY(-1px);
    border-bottom-width:6px; }
  .tbtn:active { filter:brightness(.9); transform:translateY(2px);
    border-bottom-width:2px; }
  .tbtn:disabled { opacity:.45; cursor:default; filter:none;
    transform:none; border-bottom-width:4px; }
  td.acts { white-space:nowrap; }
  td.acts .tbtn + .tbtn { margin-left:6px; }
  /* The three round icon buttons (✓ / ✕ / 🗑) used by the Inbox row are gone
     as of 2026-10-23 - the row has one blue Extract and one red Discard now,
     styled by .tbtn above. Their .iconbtn rules went with them. */
  .dt { display:flex; flex-direction:column; line-height:1.35; }
  .ddate { font-weight:600; font-size:13px; }
  .dtime { color:var(--muted); font-size:12px; }
  .attlink { color:var(--accent); text-decoration:none; font-weight:500;
    white-space:nowrap; }
  .attlink:hover { text-decoration:underline; }
  .attmiss { color:#b45309; font-weight:500; white-space:nowrap; }
  tr.controw td { border-top:none; }
  tr.controw td:nth-child(-n+6) { border-bottom-color:transparent; }
  .seqb { display:inline-block; background:var(--accent-soft);
    color:var(--accent); border-radius:4px; padding:0 5px; font-size:11px;
    font-weight:700; margin-right:6px; }
  .subjlink { color:var(--text); text-decoration:none; }
  .subjlink:hover { color:var(--accent); text-decoration:underline; }
  .syncbar { position:fixed; top:0; left:0; right:0; z-index:200;
    background:#0f172a; color:#fff; font-size:13px; padding:8px 16px;
    display:flex; align-items:center; gap:8px; }
  .syncbar .muted { color:#94a3b8; }
  .spin { width:13px; height:13px; border:2px solid #475569;
    border-top-color:#fff; border-radius:50%; display:inline-block;
    animation:sp .7s linear infinite; }
  @keyframes sp { to { transform:rotate(360deg); } }
  #toast { position:fixed; bottom:24px; left:50%; transform:translateX(-50%);
    background:#1e293b; color:#fff; padding:9px 20px; border-radius:999px;
    font-size:13px; opacity:0; pointer-events:none; transition:opacity .2s;
    z-index:99; }
  #toast.show { opacity:1; }

  /* Confirm preview. A dialog, not a page: it answers one question ("is this
     the right party, channel and delivery block?") and is dismissed either way.
     Everything inside reuses the existing card / table / btn classes. */
  /* ── Steps 2 and 3: the flow PAGE ─────────────────────────────────────────
     Not a dialog. The preview is the stepper's THIRD page, so it renders in the
     content column where the list was: the step the bar highlights and the
     thing on screen are then the same thing, which a floating modal can never
     be - and inside that modal the address block and the format buttons sat
     below the fold, which is how "the preview has no address" gets reported
     about a preview that has one. */
  .flowpage { border:1px solid var(--border); border-radius:12px; background:#fff;
    overflow:hidden; }
  .flowhead { display:flex; align-items:center; gap:12px; flex-wrap:wrap;
    padding:15px 20px; border-bottom:1px solid var(--border);
    background:#fbfdff; }
  .flowhead h3 { margin:0; font-size:15px; }
  .flowbody { padding:16px 20px 6px; }
  .flowfoot { display:flex; gap:9px; align-items:center; flex-wrap:wrap;
    padding:13px 20px; border-top:1px solid var(--border); background:#fcfdfe; }
  .pvnote { font-size:12px; color:var(--muted); line-height:1.5; margin:10px 0 0; }

  /* The format is step 3's DECISION, so it is the first thing on the page, not
     a row of buttons at the bottom of a scroll area. */
  .fmtpick { display:flex; gap:10px; margin:0 0 16px; }
  .fmtopt { flex:1 1 0; min-width:0; text-align:left; cursor:pointer;
    font-family:inherit; border:1px solid var(--border); border-radius:10px;
    background:#fff; padding:10px 13px; transition:border-color .1s, background .1s; }
  .fmtopt:hover { border-color:#bfdbfe; background:#f8fbff; }
  .fmtopt.on { border-color:var(--accent); background:#eff6ff;
    box-shadow:inset 0 0 0 1px var(--accent); }
  .fmtopt b { display:block; font-size:13px; color:var(--text); }
  .fmtopt .fmo { display:block; font-size:11.5px; color:var(--muted);
    margin-top:2px; line-height:1.45; }
  .fmtopt .fmk { float:right; width:15px; height:15px; border-radius:50%;
    border:1.5px solid #cbd5e1; margin:1px 0 0 8px; }
  .fmtopt.on .fmk { border-color:var(--accent); background:var(--accent);
    box-shadow:inset 0 0 0 3px #fff; }

  /* Two columns, so the whole header block - address included - is on screen
     without scrolling. One long column is what pushed R/W/X/AZ out of sight. */
  .pvpage { display:grid; grid-template-columns:1fr 1fr; gap:0 26px; }
  .pvgroup { grid-column:1 / -1; margin:14px 0 2px; font-size:10.5px;
    font-weight:700; letter-spacing:.05em; text-transform:uppercase;
    color:var(--muted); }
  .pvgroup:first-child { margin-top:0; }
  .pvf { display:flex; align-items:baseline; gap:9px; min-width:0;
    padding:6px 0; border-bottom:1px solid #f1f5f9; }
  .pvf .l { width:20px; flex-shrink:0; color:var(--muted); font-size:11px;
    font-variant-numeric:tabular-nums; }
  .pvf .h { width:110px; flex-shrink:0; color:var(--muted); font-size:12px; }
  .pvf .v { flex:1 1 auto; font-weight:600; font-size:12.5px; min-width:0;
    word-break:break-word; }
  .pvin { width:100%; max-width:none; padding:3px 7px; font-size:12px;
    font-family:inherit; border:1px solid #e8edf4; border-radius:6px;
    background:#fcfdff; color:var(--text); }
  .pvin:focus { outline:2px solid var(--accent-soft); border-color:var(--accent);
    background:#fff; }
  .pvin::placeholder { color:#b6c2d4; font-style:italic; }
  .pvf .v.pending { font-weight:400; font-style:italic; color:var(--muted); }
  .pvf .s { margin-left:auto; font-size:10.5px; color:var(--muted);
    white-space:nowrap; flex-shrink:0; padding-left:6px; }
  @media (max-width: 1120px){ .pvpage { grid-template-columns:1fr; } }

  /* ── Linear tab bar (2026-10-25) ──────────────────────────────────────────
     The chevron stepper is gone. Arrow-ended segments said "this is a wizard,
     in order, and you are on segment 3" - for a bar whose actual job is "which
     of the three lists are you looking at". What replaces it is a rail of
     EQUAL-width labels, the active one darker, with a short line under it that
     slides to whatever you clicked.

     Two details that make it behave rather than merely animate:
       * `--i` (the active index) is written into the container's style, so a
         fresh render puts the line in the right place with NO JavaScript and
         no flash at the left edge. Only a CLICK animates - see syncTabs().
       * the line is one absolutely-positioned element moved with `left`, so
         the browser interpolates a single number instead of animating three
         boxes at once.

     This is the ONLY bar at the top of the screen since 2026-10-28: the
     four-step stepper that borrowed these same rules is gone, because it drew
     the same pipeline a second time. What is left are the three lists and the
     tab half of these rules; the numbered-circle half went with it. */
  .tabs { --n:3; --i:0; position:relative; display:grid;
    grid-auto-flow:column;
    grid-auto-columns:1fr; margin:0 0 18px; padding:5px;
    background:var(--card); border:1px solid var(--border);
    border-radius:12px; box-shadow:0 1px 2px rgba(15,23,42,.04); }
  .tabs .tsink { position:absolute; bottom:6px; width:26px; height:2.5px;
    border-radius:2px; background:var(--accent); pointer-events:none;
    left:calc(6px + (100% - 12px) / var(--n) * (var(--i) + 0.5) - 13px);
    transition:left .34s cubic-bezier(.16,1,.3,1); }
  .tabs .ts { position:relative; z-index:1; display:flex;
    align-items:center; justify-content:center; gap:7px; min-width:0;
    padding:9px 8px 16px; border:none; background:transparent;
    border-radius:8px; font-family:inherit; font-size:12.5px; font-weight:600;
    color:var(--muted); cursor:pointer; white-space:nowrap; overflow:hidden;
    transition:color .16s ease, background .16s ease; }
  .tabs .ts:hover { color:var(--text); }
  .tabs .ts.on { color:#1d4ed8; font-weight:700;
    background:rgba(37,99,235,.06); }
  .tabs .tlb { overflow:hidden; text-overflow:ellipsis; }
  /* The count beside a tab label - a number, not a badge: it must not shift the
     label off centre, so it is smaller and muted. */
  .tabs .tnum { font-size:11px; font-weight:700; color:var(--muted);
    background:#f1f5f9; border-radius:999px; padding:0 6px; }
  .tabs .ts.on .tnum { color:#1d4ed8; background:#dbeafe; }

  /* ── Reading indicator ────────────────────────────────────────────────────
     Extraction gives no progress events - the API answers once, at the end -
     so this must NOT claim a percentage. A radar sweep says "working" and
     nothing more, which is honest; a 40%-filled bar would be invented. */
  .reading { display:flex; align-items:center; gap:14px; padding:16px 18px;
    border:1px solid var(--border); border-radius:10px; background:#fcfdfe; }
  .radar { width:38px; height:38px; border-radius:50%; flex-shrink:0;
    position:relative; background:
      radial-gradient(circle, rgba(37,99,235,.10) 0%, rgba(37,99,235,.03) 70%);
    border:1px solid #bfdbfe; }
  .radar::before { content:""; position:absolute; inset:7px; border-radius:50%;
    border:1px solid #dbeafe; }
  .radar::after { content:""; position:absolute; inset:0; border-radius:50%;
    background:conic-gradient(from 0deg, rgba(37,99,235,.55), rgba(37,99,235,0)
      42deg, rgba(37,99,235,0) 360deg);
    animation:spin 1.15s linear infinite; }
  .radar i { position:absolute; top:50%; left:50%; width:4px; height:4px;
    margin:-2px 0 0 -2px; background:var(--accent); border-radius:50%;
    animation:blip 1.4s ease-out infinite; }
  @keyframes spin { to { transform:rotate(360deg); } }
  @keyframes blip { 0% { transform:scale(1); opacity:.9; }
    70% { transform:scale(4.2); opacity:0; } 100% { opacity:0; } }
  .reading .rtxt { min-width:0; }
  .reading .rtitle { font-weight:600; font-size:13.5px; }
  .dots { display:inline-flex; gap:3px; vertical-align:middle; margin-left:2px; }
  .dots b { width:4px; height:4px; border-radius:50%; background:var(--accent);
    animation:bounce 1s infinite; }
  .dots b:nth-child(2) { animation-delay:.15s; }
  .dots b:nth-child(3) { animation-delay:.3s; }
  @keyframes bounce { 0%,80%,100% { transform:translateY(0); opacity:.4; }
    40% { transform:translateY(-3px); opacity:1; } }

  /* ── Filter row additions ─────────────────────────────────────────────── */
  .searchbox { position:relative; display:inline-flex; align-items:center; }
  .searchbox input { padding:7px 28px 7px 10px; border:1px solid var(--border);
    border-radius:7px; font-family:inherit; font-size:13px; width:210px;
    background:#fff; color:var(--text); }
  .searchbox input:focus { outline:2px solid var(--accent-soft);
    border-color:var(--accent); }
  .searchbox .clr { position:absolute; right:6px; border:none; background:none;
    color:var(--muted); cursor:pointer; font-size:12px; padding:2px; }
  .searchbox .clr:hover { color:var(--text); }
  .pager { display:flex; align-items:center; gap:6px; padding:12px 18px;
    border-top:1px solid var(--border); font-size:12.5px; color:var(--muted); }
  .pager button { border:1px solid var(--border); background:#fff;
    border-radius:6px; padding:4px 9px; font-family:inherit; font-size:12.5px;
    color:var(--text); cursor:pointer; }
  .pager button:hover:not([disabled]) { background:var(--bg); }
  .pager button[disabled] { opacity:.45; cursor:default; }
  .pager button.cur { background:var(--accent); border-color:var(--accent);
    color:#fff; font-weight:600; }
  /* Settings: one card per concern, each with its own save button */
  .setstack .setcard { margin-bottom:16px; }
  .setstack .setcard:last-child { margin-bottom:0; }

  /* Ship-To Locations - the customer master, as an editable grid */
  .shipbody { border-top:1px solid var(--border); }
  .shipwrap { overflow:auto; max-height:62vh; }
  .shiptable { border-collapse:separate; border-spacing:0; font-size:12px;
    width:max-content; min-width:100%; }
  .shiptable th { position:sticky; top:0; z-index:2; text-align:left;
    background:var(--bg); color:var(--muted); font-weight:600; font-size:11px;
    text-transform:uppercase; letter-spacing:.04em; padding:7px 8px;
    border-bottom:1px solid var(--border); white-space:nowrap; }
  .shiptable td { padding:0; border-bottom:1px solid var(--border); }
  .shiptable .shipno { position:sticky; left:0; z-index:1; padding:6px 8px;
    background:var(--bg); color:var(--muted); font-size:11px;
    font-family:ui-monospace,Consolas,monospace; }
  .shiptable .scell { width:100%; min-width:0; max-width:none; font:inherit;
    font-size:12px; color:var(--text); padding:5px 7px; border-radius:5px;
    border:1px solid transparent; background:transparent; }
  .shiptable .scell:hover { border-color:var(--border); background:#fff; }
  .shiptable .scell:focus { border-color:var(--accent); background:#fff;
    outline:2px solid var(--accent-soft); }
  /* A pair listed twice with different details: the ERP columns stay EMPTY for
     it, so the whole row is flagged until one copy is fixed. */
  .shiptable tr.shipconf .scell,
  .shiptable tr.shipconf .shipno { background:var(--danger-soft);
    color:var(--danger); }
  .shiptable th:last-child, .shiptable td:last-child { width:30px;
    text-align:center; }
  .shipmsg { padding:18px; color:var(--muted); font-size:13px; }
  .shiplegend { padding:9px 14px; font-size:12px; color:var(--danger);
    background:var(--danger-soft); border-top:1px solid var(--border); }
  .shipwarntxt { color:var(--danger); font-weight:600; }

  .daystat { display:flex; align-items:stretch; gap:10px; margin-bottom:18px;
    flex-wrap:wrap; }
  .ds { background:var(--card); border:1px solid var(--border);
    border-radius:var(--radius); padding:14px 20px; min-width:118px;
    box-shadow:0 1px 2px rgba(15,23,42,.04); }
  .ds.total { background:#0f172a; border-color:#0f172a; }
  .ds.total .dsv { color:#fff; }
  .ds.total .dsl { color:#cbd5e1; }
  .ds.go { cursor:pointer; transition:border-color .12s, box-shadow .12s; }
  .ds.go:hover { border-color:var(--accent);
    box-shadow:0 2px 8px rgba(37,99,235,.15); }
  .dsv { font-size:26px; font-weight:700; letter-spacing:-0.02em;
    line-height:1.1; }
  .dsv.accent { color:var(--accent); }
  .dsv.green { color:var(--green); }
  .dsl { font-size:12px; color:var(--muted); margin-top:3px;
    white-space:nowrap; }
  .dseq, .dsplus { display:flex; align-items:center; color:#cbd5e1;
    font-size:18px; font-weight:600; }
  .filterbar { display:flex; align-items:center; justify-content:space-between;
    gap:16px; margin-bottom:14px; flex-wrap:wrap; }
  .fleft { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  .fleft .btn { padding:8px 13px; }
  /* The filter row's controls are all as tall as the new buttons, so the row
     lines up instead of stepping. Scoped here - a global select height would
     stretch the ones inside table cells, which are meant to stay compact. */
  .filterbar select, .filterbar .searchbox input { min-height:38px; }
  .applybar { display:flex; align-items:center; justify-content:space-between;
    gap:16px; background:var(--card); border:1px solid var(--border);
    border-radius:var(--radius); padding:12px 18px; margin-bottom:16px; }
  .applybar .btn { white-space:nowrap; padding:9px 17px; font-size:13px; }
  /* Quick Convert */
  .dropzone { border:2px dashed var(--border); border-radius:var(--radius);
    padding:24px 20px 22px; text-align:center; transition:.15s;
    background:var(--bg); }
  .dropzone.over { border-color:var(--accent); background:var(--accent-soft); }
  /* The folder. Its four layers fold back one at a time, and only while a
     file is being dragged over the zone - never on plain mouse hover, so the
     animation always means one thing: "release here". */
  .dzfold { position:relative; width:240px; height:160px; margin:8px auto 0;
    cursor:pointer; perspective:1500px; outline:none; }
  .dzfold:focus-visible { box-shadow:0 0 0 3px var(--accent-soft);
    border-radius:16px; }
  .dzback { position:relative; width:100%; height:100%; background:#d97706;
    border-radius:0 16px 16px 16px; transform-origin:top;
    transition:box-shadow .3s cubic-bezier(.4,0,.2,1); }
  .dzback::after, .dzback::before { content:""; position:absolute;
    background:#d97706; }
  .dzback::after { bottom:99%; left:0; width:80px; height:16px;
    border-radius:16px 16px 0 0; }
  .dzback::before { top:-15px; left:75.5px; width:16px; height:16px;
    clip-path:polygon(0 35%, 0 100%, 50% 100%); }
  /* top:7, not the usual 4px inset — the sheets sit exactly level with the
     front panel's top edge otherwise, and anti-aliasing leaves a grey hairline
     across a folder that is supposed to look closed. */
  .dzleaf { position:absolute; left:4px; right:4px; bottom:4px; top:7px;
    border-radius:16px; transform-origin:bottom;
    transition:transform .3s cubic-bezier(.4,0,.2,1); }
  .dzl4 { background:#a1a1aa; }
  .dzl3 { background:#d4d4d8; }
  .dzl2 { background:#e4e4e7; }
  .dzfront { position:absolute; left:0; bottom:0; width:100%; height:156px;
    background:linear-gradient(to top, #f59e0b, #fbbf24);
    border-radius:16px 0 16px 16px; transform-origin:bottom;
    transition:transform .3s cubic-bezier(.4,0,.2,1),
      box-shadow .3s cubic-bezier(.4,0,.2,1); }
  .dzfront::after, .dzfront::before { content:""; position:absolute;
    background:#fbbf24; }
  .dzfront::after { bottom:99%; right:0; width:146px; height:16px;
    border-radius:16px 16px 0 0; }
  .dzfront::before { top:-10px; right:142px; width:12px; height:12px;
    clip-path:polygon(100% 14%, 50% 100%, 100% 100%); }
  .dropzone.over .dzback { box-shadow:0 20px 40px rgba(0,0,0,.2); }
  .dropzone.over .dzl4 { transform:rotateX(-20deg); }
  .dropzone.over .dzl3 { transform:rotateX(-30deg); }
  .dropzone.over .dzl2 { transform:rotateX(-38deg); }
  .dropzone.over .dzfront { transform:rotateX(-46deg) translateY(1px);
    box-shadow:inset 0 20px 40px #fbbf24, inset 0 -20px 40px #d97706; }
  .dztitle { font-size:16px; font-weight:600; margin-top:12px; }
  .dztitle .t2 { display:none; }
  .dropzone.over .dztitle .t1 { display:none; }
  .dropzone.over .dztitle .t2 { display:inline; }
  .dzsub { color:var(--muted); font-size:13px; margin-top:6px; }
  .dzsub a { color:var(--accent); font-weight:600; }
  .qfiles { display:flex; flex-direction:column; gap:6px; margin-top:14px; }
  .qfile { display:grid; grid-template-columns:1fr auto auto; gap:12px;
    align-items:center; padding:8px 12px; border:1px solid var(--border);
    border-radius:8px; font-size:13px; }
  .qopts { display:grid; grid-template-columns:repeat(3,1fr); gap:14px;
    margin:18px 0 4px; }
  .qlab { display:block; font-size:11px; font-weight:600; color:var(--muted);
    text-transform:uppercase; letter-spacing:.05em; margin-bottom:5px; }
  .qopts input { width:100%; }
  .qtable input { width:100%; max-width:none; padding:6px 8px; }
  .qtable td:first-child input { font-weight:600; }
  .qtable th:last-child, .qtable td:last-child { width:32px; }
  .qlog { background:var(--bg); border:1px solid var(--border);
    border-radius:8px; padding:10px 12px; font-size:12px; margin-top:12px;
    white-space:pre-wrap; color:var(--muted); }
  /* Checkable list of files / accounts */
  .accname { font-weight:600; font-size:13px; }
  .accres { display:flex; flex-direction:column; gap:6px; margin:12px 0;
    max-height:46vh; overflow:auto; }
  .accpick { display:flex; align-items:center; gap:10px; padding:9px 12px;
    border:1px solid var(--border); border-radius:8px; cursor:pointer;
    font-size:13px; }
  .accpick:hover { background:var(--bg); }
  .accpick.on { border-color:var(--accent); background:var(--accent-soft); }
  .accpick input { width:auto; margin:0; }
  .linkbtn { background:none; border:none; color:var(--accent);
    font-size:12px; font-weight:600; cursor:pointer; padding:2px 4px; }
  .linkbtn:hover { text-decoration:underline; }
  /* Split button: one action plus the other ways of running it. Master Data
     exports only since 2026-10-27 - the Order Upload version is chosen with the
     Full/Simple switch, because both versions can be written at once. */
  .split { position:relative; display:inline-flex; align-items:stretch;
    flex-shrink:0; }
  .split .sbm, .split .sbc { font:inherit; font-size:12.5px; font-weight:600;
    color:var(--muted); background:var(--card); border:1px solid var(--border);
    cursor:pointer; padding:5px 11px; line-height:1.35;
    white-space:nowrap; display:inline-flex; align-items:center; gap:6px; }
  .split .sbm { border-radius:8px 0 0 8px; }
  .split .sbc { border-left:none; border-radius:0 8px 8px 0;
    padding:5px 7px; font-size:10px; }
  .split .sbm:hover, .split .sbc:hover { background:var(--bg);
    color:var(--text); }
  .split.primary .sbm { background:var(--accent); border-color:var(--accent);
    color:#fff; }
  .split.primary .sbm:hover { background:#1d4ed8; color:#fff; }
  .split .sbm[disabled] { opacity:.45; cursor:default; }
  .split .sbm[disabled]:hover { background:var(--accent); }
  .splitmenu { position:absolute; top:calc(100% + 6px); right:0; z-index:60;
    min-width:250px; background:var(--card); border:1px solid var(--border);
    border-radius:10px; box-shadow:0 12px 26px rgba(15,23,42,.16);
    padding:5px; text-align:left; }
  /* Keep an open menu above the cards that follow it (the export cards sit at
     the top of a page with more cards below). */
  .split:has(.splitmenu:not([hidden])) { z-index:70; }
  .splitmenu[hidden] { display:none; }
  .splitmenu button { display:block; width:100%; text-align:left;
    background:none; border:none; font:inherit; color:var(--text);
    padding:7px 9px; border-radius:7px; cursor:pointer; }
  .splitmenu button:hover { background:var(--accent-soft); }
  .splitmenu .mi { display:block; font-size:12.5px; font-weight:600; }
  .splitmenu .md { display:block; font-size:11.5px; color:var(--muted);
    font-weight:400; margin-top:2px; line-height:1.4; }
  /* Sold-To / Ship-To pickers inside the PO table. A domain owns many
     (Sold-To, Ship-To) pairs, so the row picks the one this order went under.

     Since 2026-10-28 this is a SEARCHABLE COMBO BOX, not a <select>. One
     customer owns thousands of sites (ferguson.com: 2,246; rentacenter.com:
     1,861), and every one of them used to be an <option> inside a 120px cell -
     4,699 <option> elements on a single Inbox page, rendered so that one of
     them could be looked at. The candidates are now built when the box is
     opened, filtered as you type, and capped at PC_MAX rows. The box also
     accepts a number typed by hand: an ERP account the master does not carry is
     a real order, and the old drop-down could not express one at all. */
  td.ptd { padding:3px 5px; }
  .pcombo { position:relative; display:block; }
  .pcinput { width:100%; max-width:none; padding:3px 19px 3px 5px;
    font-size:12px; color:var(--text); }
  .pcinput.warn, .pcinput.off { border-color:var(--amber);
    background:var(--amber-soft); }
  .pccaret { position:absolute; right:2px; top:50%; transform:translateY(-50%);
    width:15px; padding:3px 0; text-align:center; font-size:8px; line-height:1;
    color:var(--muted); cursor:pointer; user-select:none; }
  .pccaret:hover { color:var(--text); }
  /* The popup lives at the END of <body>, NOT inside the cell: `table.fixed td
     { overflow:hidden }` clips anything positioned within it, and the Inbox
     table scrolls horizontally inside `.cardbody` on a narrow window.

     It is fixed to the VIEWPORT, because the table has its own horizontal
     scroller. Page coordinates made some Ship-To menus land outside the
     visible card after a Sold-To selection on a scrolled table. Any scroll
     closes it, so it never has to follow the cell. One element serves every
     picker: only one can be open at a time. */
  #pcmenu { position:fixed; z-index:4000; max-height:252px; overflow-y:auto;
    max-width:calc(100vw - 12px);
    padding:4px; background:var(--card); border:1px solid var(--border);
    border-radius:9px; box-shadow:0 12px 30px rgba(15,23,42,.17),
      0 2px 6px rgba(15,23,42,.07); }
  #pcmenu .mphead { padding:2px 7px 6px; font-size:10.5px; font-weight:700;
    letter-spacing:.04em; text-transform:uppercase; color:var(--muted);
    border-bottom:1px solid var(--border); margin-bottom:3px; }
  #pcmenu .mprow { display:flex; gap:8px; align-items:baseline; width:100%;
    padding:5px 7px; border:none; background:transparent; border-radius:6px;
    font:inherit; font-size:12.5px; color:var(--text); text-align:left;
    cursor:pointer; white-space:nowrap; overflow:hidden; }
  #pcmenu .mprow b { font-weight:600; font-variant-numeric:tabular-nums; }
  #pcmenu .mprow .mmeta { font-size:11px; color:var(--muted); overflow:hidden;
    text-overflow:ellipsis; }
  #pcmenu .mprow.on, #pcmenu .mprow:hover { background:var(--accent-soft); }
  #pcmenu .mprow.use b { color:#1d4ed8; }
  #pcmenu .mprow.use .mmeta { font-style:italic; }
  #pcmenu .mpfoot { padding:6px 7px 2px; font-size:10.5px; color:var(--muted);
    border-top:1px solid var(--border); margin-top:3px; }
  /* The ZIP of the chosen Ship-To, from the customer master. It is what tells
     two sites of one customer apart; the order's own postal code still comes
     from the PO. One short line, so it cannot push the row taller than the
     two-line cells around it. */
  .pzip { font-size:10px; line-height:1.3; color:var(--muted); margin-top:1px;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  /* ── Loading dots (2026-10-28) ────────────────────────────────────────────
     From Uiverse.io by adamgiebl, used as the placeholder a Sold-To / Ship-To
     cell shows while its account list is being fetched. It replaces a bare
     "…", which was indistinguishable from a cell that would never fill in.

     ⚠️ SCOPED to `.dots-container .dot`. This page already has a `.dot` - the
     9px status pip in every Inbox row (.dot.blue / .green / ...). The snippet
     as published styles a bare `.dot` at 20px with a box-shadow pulse, so
     pasting it in unchanged turns every status pip into a throbbing blob.
     `.dots-sm` then scales the three dots down to sit inside a table cell
     without making the row taller than its neighbours. */
  .dots-container { display:flex; align-items:center; justify-content:center;
    height:100%; width:100%; }
  .dots-container .dot { height:20px; width:20px; margin-right:10px;
    border-radius:10px; background-color:#b3d4fc;
    animation:pulse 1.5s infinite ease-in-out; }
  .dots-container .dot:last-child { margin-right:0; }
  .dots-container .dot:nth-child(1) { animation-delay:-0.3s; }
  .dots-container .dot:nth-child(2) { animation-delay:-0.1s; }
  .dots-container .dot:nth-child(3) { animation-delay:0.1s; }
  @keyframes pulse {
    0%   { transform:scale(0.8); background-color:#b3d4fc;
           box-shadow:0 0 0 0 rgba(178,212,252,0.7); }
    50%  { transform:scale(1.2); background-color:#6793fb;
           box-shadow:0 0 0 10px rgba(178,212,252,0); }
    100% { transform:scale(0.8); background-color:#b3d4fc;
           box-shadow:0 0 0 0 rgba(178,212,252,0.7); }
  }
  /* The cell-sized variant: 6px dots, 4px apart, so three of them are 26px
     wide and 8px tall - a placeholder, not a row that grows. */
  .dots-container.dots-sm { gap:0; padding:2px 0; }
  .dots-container.dots-sm .dot { height:6px; width:6px; margin-right:4px;
    border-radius:3px; }
  .dots-container.dots-sm .dot:last-child { margin-right:0; }
  /* Nothing to measure ourselves against, so the box is given a line's height
     and the dots centre in it. */
  .pwait { display:block; min-height:18px; }
  /* The multi-select customer filter (2026-10-27). A real <select multiple>
     needs ctrl-click and paints a highlighted range; a tick panel is what a
     mouse can drive. Same popup shape as .splitmenu, so it reads as part of
     the bar rather than a new kind of control. */
  .mpick { position:relative; display:inline-block; }
  .mpbtn { font:inherit; font-size:12.5px; padding:4px 9px; cursor:pointer;
    background:var(--card); color:var(--text); border:1px solid var(--border);
    border-radius:8px; max-width:260px; overflow:hidden;
    text-overflow:ellipsis; white-space:nowrap; }
  .mpbtn:hover { border-color:var(--accent); }
  .mpbtn.on { border-color:var(--accent); background:var(--accent-soft);
    color:var(--accent); font-weight:600; }
  .mpbtn .car { color:var(--muted); font-size:10px; }
  .mpmenu { position:absolute; top:calc(100% + 6px); left:0; z-index:60;
    min-width:250px; max-height:340px; overflow:auto; background:var(--card);
    border:1px solid var(--border); border-radius:10px;
    box-shadow:0 12px 26px rgba(15,23,42,.16); padding:5px; text-align:left; }
  .mpmenu[hidden] { display:none; }
  .mphead { display:flex; align-items:center; justify-content:space-between;
    gap:10px; padding:4px 8px 6px; border-bottom:1px solid var(--border);
    font-size:11.5px; }
  .mpmenu label { display:flex; align-items:center; gap:8px; padding:5px 8px;
    border-radius:7px; cursor:pointer; font-size:12.5px; }
  .mpmenu label:hover { background:var(--accent-soft); }
  .mpmenu label input { margin:0; cursor:pointer; }
  .mpmenu label .ell { overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap; }
  .mpick:has(.mpmenu:not([hidden])) { z-index:70; }
  /* The per-row address boxes are gone (2026-10-23): the delivery address and
     the numbered name / street lines are typed on the preview page, where the
     PO's own values are visible as placeholders. */
  /* The folded half of the Ship-To block (O-Q, S-V, W, X, AZ). Twelve inputs
     on every row would make the Inbox unreadable; most orders only ever need
     N and R, so the rest live behind this disclosure and remember nothing
     between renders - it is a per-row inspection, not a preference. */
  details.shipmore { margin-top:3px; }
  details.shipmore > summary {
    cursor:pointer; font-size:10.5px; color:var(--muted); padding:2px 0;
    list-style:none; user-select:none; }
  details.shipmore > summary::-webkit-details-marker { display:none; }
  details.shipmore > summary:before { content:"\25b8 "; }
  details.shipmore[open] > summary:before { content:"\25be "; }
  details.shipmore > summary:hover { color:var(--ink); }
  details.shipmore > summary .filled { color:var(--accent); font-weight:600; }
  div.shipgrid {
    display:grid; grid-template-columns:1fr 1fr; gap:3px 6px;
    padding:5px 0 2px; }
  div.shipgrid label {
    display:block; font-size:10px; color:var(--muted);
    text-transform:uppercase; letter-spacing:.02em; }
  div.shipgrid input, div.shipgrid select {
    width:100%; padding:2px 4px; font-size:11px; margin-top:1px; }
  .prow { display:flex; align-items:center; gap:10px; flex-wrap:wrap;
    margin:14px 0 0; }
  .prow > label { font-size:12px; color:var(--muted); display:inline-flex;
    align-items:center; gap:6px; }
  .prow select { min-width:170px; max-width:260px; }
  /* The two account boxes on the Quick Convert card: same component as the
     Inbox rows, so they get the same width the drop-downs had. */
  .prow .pcombo { width:210px; }
  .prow .pcinput { width:100%; max-width:none; padding:5px 20px 5px 8px;
    font-size:13px; }
  .chnchip { display:inline-block; padding:1px 7px; border-radius:999px;
    font-size:11px; font-weight:600; background:var(--bg);
    border:1px solid var(--border); color:var(--muted); }
  .chnchip.set { background:var(--green-soft); border-color:#bbf7d0;
    color:var(--green); }
  .fmtchip { display:inline-block; padding:1px 7px; border-radius:999px;
    font-size:11px; font-weight:600; background:var(--bg);
    border:1px solid var(--border); color:var(--muted); margin-right:6px; }
  .fmtchip.simple { background:var(--violet-soft); border-color:#ddd6fe;
    color:var(--violet); }
  .dupflag { color:var(--danger); font-weight:600; font-size:12.5px; }
  /* A keyword hint is advisory, so it is muted, not red - the red glyph has to
     keep meaning "this PO number really did arrive twice". */
  .duphint { color:var(--amber); font-weight:600; font-size:12.5px; }

  select, input[type=text] { padding:5px 8px; border:1px solid var(--border);
    border-radius:6px; font-family:inherit; font-size:13px; background:#fff;
    color:var(--text); max-width:170px; }
  select:focus, input:focus { outline:2px solid var(--accent-soft);
    border-color:var(--accent); }
  input[type=checkbox] { width:16px; height:16px; accent-color:var(--accent); }

  /* ── Buttons ──────────────────────────────────────────────────────────────
     The "uiverse" tile the desk sent: a white card with a deep soft shadow
     that lifts on hover and fills with a blue gradient, with the label's
     tooltip sliding up above it.

     Two deliberate departures from the snippet, both because it is a CARD,
     not a button:
       * no fixed 150x50 - this page puts four or five buttons in one filter
         row; a 150px tile each would wrap it onto three lines. The height is
         38px and the width is intrinsic, so "Sync this date" is as wide as its
         own text.
       * font 12.5px, not 17px - at 17px a toolbar row is taller than a table
         row, and the two sit next to each other.

     `.tbtn` (the blue Extract / red Discard in the table) is deliberately NOT
     affected: it keeps the 3D-key look it was given. */
  .btn { position:relative; display:inline-flex; align-items:center;
    justify-content:center; gap:7px; min-height:38px; padding:8px 15px;
    border-radius:10px; border:1px solid #eef0f4; background:#fff;
    color:var(--text); font-family:inherit; font-size:12.5px; font-weight:600;
    line-height:1.2; cursor:pointer; margin-right:6px;
    box-shadow:0 10px 10px rgba(0,0,0,.08);
    transition:all .2s cubic-bezier(.68,-.55,.265,1.55); }
  .btn:hover { background:linear-gradient(320deg, #034d92, #003cff);
    border-color:#0038e6; color:#fff; transform:translateY(-1px);
    box-shadow:0 14px 14px rgba(0,60,255,.20); }
  .btn:active { transform:translateY(1px);
    box-shadow:0 5px 6px rgba(0,0,0,.12); }
  .btn.primary { background:linear-gradient(320deg, #034d92, #003cff);
    border-color:#0038e6; color:#fff; }
  .btn.primary:hover { filter:brightness(1.09); color:#fff; }
  .btn.danger { color:#b91c1c; border-color:#fee2e2; }
  .btn.danger:hover { background:linear-gradient(320deg, #b91c1c, #ef4444);
    border-color:#ef4444; color:#fff; }
  .btn[disabled], .btn:disabled { opacity:.5; cursor:default; box-shadow:none; }
  .btn[disabled]:hover, .btn:disabled:hover { background:#fff; color:var(--text);
    transform:none; box-shadow:none; filter:none; }
  /* The tooltip that slides up on hover. One shared element, positioned in JS:
     the per-button copy in the snippet is clipped by `overflow:hidden` on the
     cards it would sit inside. */
  .btntip { position:fixed; z-index:210; max-width:290px; padding:6px 9px;
    /* max-content, not shrink-to-fit: a fixed box with only `left` set is
       squeezed into the space left of the window edge, so a tooltip on a
       right-hand column wrapped into a three-line ribbon ~100px wide. The
       caller clamps `left` instead and moves the arrow. */
    width:max-content;
    background:#fff; color:#0f172a; border:1px solid #e8edf4;
    border-radius:5px; box-shadow:0 10px 10px rgba(0,0,0,.10);
    font-size:12px; font-weight:500; line-height:1.4; text-align:left;
    white-space:normal; pointer-events:none; opacity:0;
    transform:translate(-50%,-100%) scale(.94);
    transition:all .3s cubic-bezier(.68,-.55,.265,1.55); }
  .btntip.on { opacity:1; transform:translate(-50%,-100%) scale(1); }
  .btntip.below { transform:translate(-50%,0) scale(.94); }
  .btntip.below.on { transform:translate(-50%,0) scale(1); }
  .btntip::after { content:""; position:absolute; bottom:-3px;
    left:var(--arrow, 50%);
    width:8px; height:8px; background:#fff; border-right:1px solid #e8edf4;
    border-bottom:1px solid #e8edf4;
    transform:translateX(-50%) rotate(45deg); }
  .btntip.below::after { bottom:auto; top:-3px; border:none;
    border-left:1px solid #e8edf4; border-top:1px solid #e8edf4; }
  /* The same bubble, in its "explain a screen" layout: a paragraph rather than
     a label, so it needs a wider box, real line height and left-aligned lines.
     One element, one positioning path - a second tooltip would drift from this
     one the first time either got touched. */
  .btntip.rich { max-width:340px; padding:10px 12px 11px; font-size:12.5px;
    font-weight:400; line-height:1.55; box-shadow:0 14px 34px rgba(15,23,42,.16);
    border-color:#e2e8f0; }
  .btntip.rich b { font-weight:700; color:#0b1220; }
  .btntip.rich code { font-family:ui-monospace, Menlo, Consolas, monospace;
    font-size:11.5px; background:#f1f5f9; padding:1px 4px; border-radius:4px; }

  /* The "?" that carries that paragraph. It has to be readable in a heading
     without making the heading taller, so it is an inline-flex box the size of
     the lower-case height rather than a padded chip. */
  .faq { display:inline-flex; align-items:center; justify-content:center;
    width:16px; height:16px; margin-left:7px; border-radius:50%;
    color:#94a3b8; cursor:help; flex:0 0 auto; vertical-align:middle;
    transform:translateY(-1px); transition:color .14s ease,
      background .14s ease; }
  .faq svg { width:15px; height:15px; display:block; }
  .faq:hover, .faq:focus { color:#1d4ed8; background:#eff6ff; outline:none; }
  .faq:focus-visible { box-shadow:0 0 0 2px #dbeafe; }
  h1 .faq, h3 .faq { transform:translateY(-2px); }
  /* The head row already has a 12px gap, so the marker's own margin made the
     two look unrelated. Pull it back to a normal word space. */
  #titlefaq { margin-left:-5px; display:flex; align-items:center; }

  /* ── Full-screen activity indicator ───────────────────────────────────────
     Used while a mailbox is (re)read. Reading is done by Outlook through COM
     and can take a minute; the old toast said "Collecting…" and then nothing
     moved, which reads as a freeze.

     Determinate when the server knows a total (a ring that fills), three dots
     when it does not - a percentage that cannot be computed is worse than no
     percentage, because it teaches people not to trust the indicator. */
  #busy { position:fixed; inset:0; z-index:300; display:none;
    background:rgba(15,23,42,.40); align-items:center; justify-content:center; }
  #busy.open { display:flex; }
  #busy .busybox { background:#fff; border-radius:14px; padding:20px 24px;
    min-width:300px; max-width:420px; box-shadow:0 24px 60px rgba(15,23,42,.30);
    display:flex; align-items:center; gap:18px; }
  #busy .busytitle { font-size:14px; font-weight:700; }
  #busy .busysub { font-size:12px; color:var(--muted); margin-top:4px;
    line-height:1.45; }
  .ringwrap { position:relative; width:54px; height:54px; flex-shrink:0; }
  .ring { width:54px; height:54px; transform:rotate(-90deg); }
  .ring circle { fill:none; stroke-width:5; }
  .ring .bg { stroke:#e2e8f0; }
  .ring .fg { stroke:var(--accent); stroke-linecap:round;
    transition:stroke-dashoffset .3s ease; }
  .ringwrap .pct { position:absolute; inset:0; display:flex;
    align-items:center; justify-content:center; font-size:11.5px;
    font-weight:700; color:var(--accent); }
  .fdots { display:flex; gap:7px; width:54px; height:54px; align-items:center;
    justify-content:center; }
  .fdots b { width:10px; height:10px; border-radius:50%;
    background:var(--accent); animation:fdots 1.1s infinite ease-in-out; }
  .fdots b:nth-child(2) { animation-delay:.16s; }
  .fdots b:nth-child(3) { animation-delay:.32s; }
  @keyframes fdots { 0%,80%,100% { transform:scale(.5); opacity:.4; }
    40% { transform:scale(1); opacity:1; } }

  .empty { color:var(--muted); padding:40px; text-align:center;
    background:var(--card); border:1px dashed var(--border);
    border-radius:var(--radius); font-size:14px; }
  .datehead { font-size:13px; font-weight:600; color:var(--muted);
    margin:22px 0 8px; text-transform:uppercase; letter-spacing:.05em; }
  .muted { color:var(--muted); }

  /* ── Dashboard (2026-10-25) ───────────────────────────────────────────────
     Three numbers, one line, one breakdown. The screen it replaces was a wall
     of five tables that all answered "what happened" and none that answered
     "how are we doing" - so the numbers moved to the top, the trend became a
     picture, and only the customer split stayed a table. */
  .kpirow.dash { gap:14px; margin-bottom:16px; }
  .kpi2 { position:relative; background:var(--card); border:1px solid var(--border);
    border-radius:14px; padding:16px 18px 14px;
    box-shadow:0 1px 2px rgba(15,23,42,.04); overflow:hidden; }
  .kpi2::after { content:""; position:absolute; left:0; top:0; bottom:0; width:3px;
    background:var(--accent); opacity:.85; }
  .kpi2.g::after { background:var(--green); }
  .kpi2.a::after { background:var(--amber); }
  .kpi2 .klab { font-size:11px; font-weight:700; letter-spacing:.07em;
    text-transform:uppercase; color:var(--muted); }
  .kpi2 .kval { font-size:31px; font-weight:750; letter-spacing:-.03em;
    line-height:1.05; margin-top:7px; font-variant-numeric:tabular-nums; }
  .kpi2 .kval small { font-size:12.5px; font-weight:600; color:var(--muted);
    letter-spacing:0; margin-left:6px; }
  .kpi2 .ksub { font-size:12px; color:var(--muted); margin-top:7px; }
  /* 环比: the badge sits in the card's own corner so the three of them line up
     across the row, and it reads the period it is comparing against. */
  .delta { position:absolute; top:13px; right:13px; display:inline-flex;
    align-items:center; gap:4px; font-size:11.5px; font-weight:700;
    padding:2px 8px; border-radius:999px; white-space:nowrap; }
  .delta .ar { font-size:9px; line-height:1; }
  .delta.up { color:#15803d; background:var(--green-soft); }
  .delta.down { color:#b91c1c; background:var(--danger-soft); }
  .delta.flat { color:var(--muted); background:#f1f5f9; }

  .chartcard { padding:0; }
  .charthead { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap;
    padding:14px 18px 4px; }
  .charthead h3 { margin:0; font-size:15px; font-weight:600; }
  .charthead .legend { margin-left:auto; display:flex; align-items:center;
    gap:6px; font-size:12px; color:var(--muted); }
  .charthead .legend i { width:9px; height:9px; border-radius:50%;
    background:var(--accent); display:inline-block; }
  .chartwrap { padding:6px 14px 12px; }
  /* The drawing keeps its own aspect ratio and is scaled uniformly: the box
     fixes the ratio, so 30 points stay 30 points and the labels never stretch.
     Text is sized in viewBox units (12 of 1000), which reads as ~12px at the
     card width this dashboard is meant for. */
  .trendwrap { width:100%; aspect-ratio:1000 / 260; }
  svg.trend { display:block; width:100%; height:100%; }
  svg.trend .gl { stroke:#eef2f7; stroke-width:1; }
  svg.trend .zl { stroke:#e2e8f0; stroke-width:1; }
  svg.trend .lab { fill:#94a3b8; font-size:12px;
    font-variant-numeric:tabular-nums; }
  svg.trend .ln { fill:none; stroke:url(#tline); stroke-width:2.6;
    stroke-linecap:round; stroke-linejoin:round; }
  svg.trend .dot { fill:#fff; stroke:var(--accent); stroke-width:2.2;
    transition:r .12s ease, stroke-width .12s ease; }
  svg.trend .dot.last { fill:var(--accent); stroke:#fff; stroke-width:2.6; }
  svg.trend .hit { fill:transparent; cursor:pointer; }
  svg.trend g.pt:hover .dot { r:5; stroke-width:3; }

  /* Customer share: a bar per customer, not a pie - the question is "how much
     of the total is this one", and lengths compare better than angles. */
  .share { display:flex; align-items:center; gap:14px; padding:10px 18px;
    border-bottom:1px solid #f1f5f9; }
  .share:last-child { border-bottom:none; }
  .share .nm { width:190px; flex-shrink:0; font-size:13px; font-weight:600;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .share .bar { flex:1 1 auto; min-width:60px; height:8px; border-radius:99px;
    background:#f1f5f9; overflow:hidden; }
  .share .bar i { display:block; height:100%; border-radius:99px;
    background:linear-gradient(90deg,#93c5fd,#2563eb); }
  .share .n { width:40px; text-align:right; font-weight:700; font-size:13px;
    font-variant-numeric:tabular-nums; }
  .share .pc { width:56px; text-align:right; font-size:12px; color:var(--muted);
    font-variant-numeric:tabular-nums; }

  /* ── Read list (Inbox tab 2) ──────────────────────────────────────────────
     One row per order document that has a reading on disk. The row expands in
     place rather than opening a page: comparing two POs' addresses is the
     reason this screen exists, and a page can only show one of them. */
  .rlrow { border-bottom:1px solid #f1f5f9; }
  .rlrow.open { background:#fbfdff; }
  .rlrow:last-child { border-bottom:none; }
  .rlmain { display:grid; align-items:center; gap:12px; padding:11px 18px;
    cursor:pointer; grid-template-columns:
      14px minmax(0,1fr) 150px 132px 116px 210px; }
  .rlmain:hover { background:#f8fafc; }
  .rlcar { color:#94a3b8; font-size:9px; transition:transform .18s ease; }
  .rlrow.open .rlcar { transform:rotate(90deg); }
  .rlfname { font-weight:600; font-size:13px; overflow:hidden;
    text-overflow:ellipsis; white-space:nowrap; }
  .rlmeta { font-size:11.5px; color:var(--muted); margin-top:2px;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .rlcell { font-size:12.5px; color:#475569; overflow:hidden;
    text-overflow:ellipsis; white-space:nowrap; }
  .rlcell.mono { font-family:Consolas,'Courier New',monospace; font-size:11.5px; }
  .ftype { display:inline-block; font-size:10.5px; font-weight:700;
    letter-spacing:.03em; padding:1px 7px; border-radius:5px;
    background:#f1f5f9; color:#475569; }
  .ftype.pdf { background:#fef2f2; color:#b91c1c; }
  .ftype.xls { background:#f0fdf4; color:#15803d; }
  .rlacts { display:flex; gap:8px; justify-content:flex-end;
    align-items:center; }
  .btn.sm { min-height:28px; padding:4px 11px; font-size:11.5px;
    border-radius:8px; box-shadow:0 2px 4px rgba(15,23,42,.07);
    margin-right:0; }
  /* Full / Simple as one segmented control with a spring-loaded thumb, in the
     place of two buttons. The reference is glass on a dark translucent panel;
     on a white row pure glass just reads as a grey smudge, so the track is a
     soft inset and the thumb is the only bright surface - that keeps the depth
     cue without fighting the rest of the page. Only the colour and the depth
     were retuned: the geometry, the checked-driven thumb and the overshoot are
     the reference's. */
  .seg { position:relative; display:inline-flex; width:124px; padding:3px;
    border-radius:999px; background:#e7ecf3; border:1px solid #dce4ee;
    box-shadow:inset 0 1px 2px rgba(15,23,42,.07); }
  .segthumb { position:absolute; top:3px; bottom:3px; left:3px;
    width:calc(50% - 3px); border-radius:999px;
    background:linear-gradient(180deg,#fff,#f7f9fc);
    box-shadow:0 1px 2px rgba(15,23,42,.10), 0 3px 8px rgba(15,23,42,.06),
      inset 0 1px 0 #fff;
    transition:transform .4s cubic-bezier(.68,-.35,.27,1.35),
      width .32s cubic-bezier(.4,0,.2,1),
      box-shadow .25s ease; }
  .seg:has(.segopt:last-child input:checked) .segthumb {
    transform:translateX(100%); }
  /* Both halves ticked (2026-10-27): the thumb stretches across the whole
     track. Left/right means "this one", the full width means "both", and the
     two labels stay where they were, so nothing about the control moves. The
     rule needs a step more specificity than the right-hand one above - the
     second :has() is what provides it, not !important.
     ⚠️ :FIRST-OF-TYPE, not :first-child: the thumb <span> is the first child
     of .seg, so the first label is never a :first-child and the rule silently
     matches nothing (that is exactly how the first attempt failed). */
  .seg:has(.segopt:first-of-type input:checked):has(.segopt:last-of-type input:checked) .segthumb {
    transform:none; width:calc(100% - 6px); }
  .seg:hover .segthumb { box-shadow:0 2px 4px rgba(15,23,42,.12),
    0 5px 12px rgba(15,23,42,.08), inset 0 1px 0 #fff; }
  .segopt { position:relative; flex:1 1 0; display:flex; }
  /* Out of the flow but still in the tab order: the radio is the control, the
     label is only its skin. */
  .segopt input { position:absolute; left:0; top:0; margin:0; opacity:0;
    pointer-events:none; }
  .seglab { display:flex; align-items:center; justify-content:center;
    width:100%; height:22px; border-radius:999px; font-size:11.5px;
    font-weight:600; color:#64748b; cursor:pointer; user-select:none;
    white-space:nowrap; transition:color .22s ease; }
  .segopt input:checked + .seglab { color:#1d4ed8; font-weight:700; }
  .segopt:hover input:not(:checked) + .seglab { color:#334155; }
  .segopt input:focus-visible + .seglab {
    box-shadow:0 0 0 2px rgba(37,99,235,.35); }
  /* Verbatim width: the label becomes "Writing…" while the file is written, and
     a button that grew would shove the switch beside it sideways. */
  .genbtn { width:76px; padding:4px 0; }
  /* The spinner is built for a light surface (dark ring, white arc); on the blue
     primary button that reads backwards, so flip it. flex:0 0 auto matters - as
     a flex item it shrank whenever the label was close to the button's width,
     and a 4x11 box with border-radius:50% is a capsule, not a ring. */
  .genbtn .spin { flex:0 0 auto; width:11px; height:11px;
    border-color:rgba(255,255,255,.45); border-top-color:#fff; }
  .btn:disabled { pointer-events:none; cursor:default; }
  .btn.working { opacity:.8; }
  /* Frozen while the write is in flight - changing the format then would say
     something about a file that is already being written. */
  .seg.busy { opacity:.55; pointer-events:none; }
  .seg.busy .segthumb { animation:segpulse .6s ease-out; }
  @keyframes segpulse {
    0%, 100% { box-shadow:0 1px 2px rgba(15,23,42,.10); }
    50% { box-shadow:0 2px 10px rgba(37,99,235,.30); }
  }
  .rldetail { padding:2px 18px 16px 44px; }
  /* The per-order table (2026-10-28). One document can hold several POs, and
     then the dates / address cannot be shown once - so each order is a row of
     its own, in both the step-3 preview and the Read tab. */
  .ordtab { width:100%; border-collapse:collapse; font-size:12.5px; }
  .ordtab th { text-align:left; font-weight:600; color:var(--muted);
    padding:6px 10px; border-bottom:1px solid var(--border);
    white-space:nowrap; }
  .ordtab td { padding:6px 10px; border-bottom:1px solid var(--border);
    vertical-align:top; }
  .ordtab tr:last-child td { border-bottom:none; }
  .ordtab .num { text-align:right; font-variant-numeric:tabular-nums; }
  .ordbox { border:1px solid var(--border); border-radius:10px;
    margin:0 0 14px; overflow:hidden; background:var(--card); }
  .ordbox .ordhead { padding:7px 10px; background:var(--bg);
    border-bottom:1px solid var(--border); font-weight:600; font-size:12.5px; }
  .rlgrid { display:grid; gap:0 20px;
    grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); }
  .rlf { display:flex; gap:9px; padding:5px 0; font-size:12.5px;
    border-bottom:1px dashed #eef2f7; }
  .rlf .k { width:92px; flex-shrink:0; color:var(--muted); }
  .rlf .v { font-weight:600; min-width:0; word-break:break-word; }
  .rlf .v.no { font-weight:400; color:#b6c2d4; font-style:italic; }
  .rlnote { font-size:11.5px; color:var(--muted); margin:8px 0 0; }
  .rlwarn { display:inline-flex; align-items:center; gap:5px; font-size:11px;
    font-weight:700; color:#92400e; background:var(--amber-soft);
    border:1px solid #fde68a; border-radius:999px; padding:1px 8px; }

  /* The date the Inbox answers for. It moved out of the sidebar when the menu
     became a 62px rail - a date field cannot be shown in 62px, and hiding the
     only control that changes the screen behind a hover was worse than moving
     it into the row of filters it belongs with. */
  .dpick { min-height:38px; padding:6px 10px; border:1px solid var(--border);
    border-radius:8px; font-family:inherit; font-size:13px; color:var(--text);
    background:#fff; cursor:pointer; }
  .dpick:hover { border-color:#cbd5e1; }
  .dpick:focus { outline:2px solid var(--accent-soft);
    border-color:var(--accent); }
</style>
</head>
<body>
<div class="layout">
  <!-- The rail reserves 62px; the plate inside it widens over the page on
       hover. Two elements because the width that RESERVES space and the width
       that is DISPLAYED must be different ones - otherwise hovering the menu
       reflows every table behind it. -->
  <div class="sidewrap">
    <div class="sidebar" id="sidebar">
      <button type="button" class="brand" id="brandbtn"
        onclick="toggleSidebar()" aria-expanded="false" aria-controls="sidebar"
        title="Open the menu">
        <div class="blogo">OF</div>
        <div class="bfull">Order<span>Flow</span>
          <div class="brandsub">Order Management
            <span class="buildtag" title="Build version">__BUILD__</span></div>
        </div>
      </button>
      __NAV__
    </div>
  </div>
  <div class="main">
    <div class="pagehead">
      <div style="display:flex; align-items:center; gap:12px; min-width:0;">
        <button class="railbtn" id="railbtn" title="Show / hide the menu"
          onclick="toggleRail()">&#9776;</button>
        <h1 id="title">Inbox</h1>
        <!-- The screen's explanation, as a marker instead of a paragraph under
             the first card. Filled by render() so every screen gets the same
             treatment in the same place. -->
        <span id="titlefaq" class="titlefaq"></span>
      </div>
      <div style="display:flex; align-items:center; gap:14px;">
        <div class="meta" id="meta"></div>
        <!-- "PO reading is not connected" lives here, in the top corner of the
             two screens that read POs. Filled by renderApiWarn(). -->
        <span id="apiwarn"></span>
      </div></div>
    <!-- First paint. `load()` has not run yet, so this is what the user sees
         until /api/dashboard lands - about 60-80 ms warm, longer on a cold
         start while the masters are read. Same dots component the pickers use,
         at its full size. render() replaces it on the first answer. -->
    <div id="content"><div class="dots-container" style="min-height:200px"
      role="status" aria-label="Loading the dashboard"><span class="dot"></span><span
      class="dot"></span><span class="dot"></span></div></div>
  </div>
</div>
<!-- The account popup. It is here, at the end of the document, rather than
     inside the cell that opens it: `table.fixed td { overflow:hidden }` clips
     anything positioned within it, and the table scrolls sideways inside
     `.cardbody`. Shipped empty and hidden so the element exists from the first
     paint - pcBox() creates it if an older page did not. -->
<div id="pcmenu" hidden></div>
<script>
let DATA = null;
let TAB = 'today';
function localToday(){
  const d = new Date();
  return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+
    String(d.getDate()).padStart(2,'0');
}
let SELDATE = localToday();
const STATUSES = ['Not yet','Pending','Done','Rejected'];
const TITLES = {today:'Inbox',
  notmypo:'Discarded', completed:'Completed — Order Upload', history:'Dashboard',
  master:'Customer Master',
  codes:'Material Codes', settings:'Settings',
  quick:'Quick Convert — PO file to Order Upload'};

function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function dispName(m){
  return m.customer || (m.sender_domain ? '@'+m.sender_domain : '(unknown)');
}

function fmtDate(iso){
  if (!iso) return '(no date)';
  // date-only strings: parse as local time to avoid UTC off-by-one
  const d = iso.length === 10
    ? new Date(+iso.slice(0,4), +iso.slice(5,7)-1, +iso.slice(8,10))
    : new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleDateString('en-US',
    {weekday:'short', month:'short', day:'numeric', year:'numeric'});
}

function fmtTime(iso){
  if (!iso) return '-';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleTimeString('en-US', {hour:'numeric', minute:'2-digit'});
}

function fmtDT(iso){
  if (!iso) return '-';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleDateString('en-US', {month:'short', day:'numeric'}) +
    ', ' + fmtTime(iso);
}

function fmtDT2(iso){
  // Show date/time on two lines (readability)
  if (!iso) return '<span class="muted">—</span>';
  const d = new Date(iso);
  if (isNaN(d)) return esc(iso);
  return '<div class="dt"><span class="ddate">'+
    d.toLocaleDateString('en-US', {month:'short', day:'numeric'})+
    '</span><span class="dtime">'+fmtTime(iso)+'</span></div>';
}

async function api(path, body){
  const r = await fetch(path, body ? {method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {});
  return r.json();
}

let SYNCPOLL = null;

// Which Order Upload files to produce: 'full' = the Standard Order Upload form
// (config\\erp_template.XLSX), 'simple' = a plain sheet with four columns
// (PO # / Material / Sales Quantity / Unit Price).
//
// A LIST, not one value (2026-10-27). The two are not alternatives: a desk that
// uploads the full form to ERP and also wants the simple sheet for keying by
// hand ticks both and gets both files out of ONE action. `['full']` is the
// default, so nothing changes for anyone who does not touch the switch.
//
// Kept here so Confirm and Quick Convert share one choice; saved server-side, so
// it survives a reload. The server normalises whatever it is given, so the
// order of this list never matters - only which entries are in it.
let ERPFMTS = null;   // pending choice; null = whatever the server last said

const FMT_ORDER = ['full', 'simple'];
const FMT_LABEL = {full: 'Full form', simple: 'Simple'};

// Any shape -> ['full'] / ['simple'] / ['full', 'simple'], never empty.
function normFmts(v){
  const raw = Array.isArray(v) ? v : (v ? [v] : []);
  const picked = [];
  raw.forEach(x => {
    const s = String(x == null ? '' : x).trim().toLowerCase();
    if (!s) return;
    const f = s.charAt(0) === 's' ? 'simple' : 'full';
    if (picked.indexOf(f) < 0) picked.push(f);
  });
  if (!picked.length) picked.push('full');
  return FMT_ORDER.filter(f => picked.indexOf(f) >= 0);
}

function erpFmts(){
  return normFmts(ERPFMTS ||
    (DATA && DATA.erp_formats) ||
    (DATA && DATA.erp_format));
}

// The primary file, for the few corners that can only name one (a toast, the
// order-upload badge). Writers must send the whole list.
function erpFmt(){ return erpFmts()[0]; }

function fmtOn(f){ return erpFmts().indexOf(f) >= 0; }

const FMT_TITLE = {
  full: 'Full version — the Standard Order Upload form: P/O No., Sales Org / '+
        'Distr. Channel / Division, Sold-To-Party, Ship-To-Party, Material, '+
        'Sales Quantity and Unit Price, with every other column kept as '+
        'config\\\\erp_template.XLSX has it.',
  simple: 'Simple version — four columns only: PO #, Material, '+
          'Sales Quantity, Unit Price. No template involved.'
};

const FMT_SHORT = {
  full: 'The ERP form: P/O No., sales area, Sold-To / Ship-To, Material, '+
        'Sales Quantity, Unit Price.',
  simple: 'Four columns only: PO #, Material, Sales Quantity, Unit Price.'
};

// "Full form + Simple" - what the two checkboxes currently mean, in words.
function fmtName(){
  return erpFmts().map(f => FMT_LABEL[f]).join(' + ');
}

// ── Master-data export ──
// Both Master Data screens export the SAME file the upload expects, built from
// the server's own column schema - so the two can never drift apart. All and
// "filtered" are one button plus a caret, matching the split button already
// used for the Order Upload version.
function exportSplit(o){
  o = o || {};
  const id = 'exp-' + (o.id || 'x');
  return '<span class="split">'+
    '<button class="sbm" title="'+esc(o.title||'')+'" onclick="'+
      'doExport(\\''+o.set+'\\',\\'all\\',\\''+id+'\\')">'+
      (o.label || 'Export')+'</button>'+
    '<button class="sbc" title="More export options" '+
    'onclick="splitOpen(event,\\''+id+'\\')">&#9660;</button>'+
    '<div class="splitmenu" id="'+id+'" hidden>'+
    '<button onclick="doExport(\\''+o.set+'\\',\\'all\\',\\''+id+'\\')">'+
      '<span class="mi">Export all</span>'+
      '<span class="md">every record in the master</span></button>'+
    '<button onclick="doExport(\\''+o.set+'\\',\\'filter\\',\\''+id+'\\')"'+
      (o.canFilter?'':' disabled')+'>'+
      '<span class="mi">Export what is listed</span>'+
      '<span class="md">'+(o.filterHint || 'only the rows on screen')+
      '</span></button>'+
    '</div></span>';
}

function doExport(set, scope, id){
  closeSplits();
  // The filters live in JS state, so they travel as query parameters: the
  // server builds the file from the same columns either way.
  // Both customer grids filter on the server, so the search text travels as-is
  // instead of enumerating every matching row. Each grid's own box is used -
  // reading SHIP.q for the domain table exported the wrong rows.
  const s = new URLSearchParams({set: set, scope: scope});
  if (scope === 'filter'){
    if (set === 'materials'){
      const ids = (shownCodes() || []).map(c => c.code);
      if (!ids.length){ alert('Nothing is listed under the current filter, so '+
        'there is nothing to export. Clear the search or export all.'); return; }
      ids.forEach(c => s.append('code', c));
    } else {
      const q = ((set === 'domains' ? DOM.q : SHIP.q) || '').trim();
      const what = set === 'domains' ? 'domain' : 'Ship-To';
      if (!q){ alert('The '+what+' list is not filtered, so "what is listed" '+
        'and "all" are the same file. Use Export all.'); return; }
      s.append('q', q);
    }
  }
  toast(scope === 'filter' ? 'Building the filtered file…'
                           : 'Building the export…');
  // A real navigation, not fetch: the browser then handles the file itself
  // (download shelf, file name) exactly as it does for the Order Upload.
  window.location = '/api/master_export?' + s.toString();
}

// What the Material Codes list is currently showing. The Ship-To grid needs no
// equivalent: its filter is applied by the server from SHIP.q, which travels to
// the export unchanged.
function shownCodes(){
  if (!CODES || !CODES.materials) return [];
  const q = CODEQ.trim().toUpperCase();
  let out = CODES.materials;
  if (CODECAT) out = out.filter(
    c => (c.product || '(uncategorised)') === CODECAT);
  if (q) out = out.filter(c =>
    (c.code||'').toUpperCase().includes(q) ||
    (c.product||'').toUpperCase().includes(q) ||
    (c.cate1||'').toUpperCase().includes(q) ||
    (c.cate2||'').toUpperCase().includes(q));
  return out;
}

// ── Split button ──
// A split button is one action plus the other ways of running it. Since
// 2026-10-27 the Order Upload version is no longer an either/or, so this is used
// by the Master Data export cards only - Quick Convert draws the Full/Simple
// switch instead of a caret that offered "the other one".

function splitOpen(ev, id){
  ev.stopPropagation();
  const m = document.getElementById(id);
  if (!m) return;
  const reopened = m.hidden;
  closeSplits();
  m.hidden = !reopened;
}

// The onclick for the left half of a split button. The Master Data export
// cards pass their own action, so this is only the "open the menu" spelling.
function fnSplit(id){
  return "splitOpen(event, 'split-" + id + "')";
}

function closeSplits(){
  document.querySelectorAll('.splitmenu').forEach(m => { m.hidden = true; });
}
document.addEventListener('click', closeSplits);

// Record the choice. `list` is whatever the control produced; the server
// normalises it and answers with the canonical list, which is then what the
// page shows - so a reload can never disagree with the last click.
async function setErpFmts(list){
  const want = normFmts(list);
  // Show the new state straight away, then save it. Deliberately does NOT
  // call load(): that re-renders the Settings form from the server's copy and
  // would wipe anything typed there but not yet saved.
  ERPFMTS = want;
  render();
  const r = await api('/api/erp_format', {formats: want});
  if (r && r.error){ alert(r.error); ERPFMTS = null; render(); return; }
  ERPFMTS = null;
  if (DATA) DATA.erp_formats = (r && r.formats) || want;
}

// ── One switch for both screens: Full / Simple, and BOTH at once ───────────
// The component is the same `.seg` it always was, with the same track, thumb
// and labels - only the inputs are checkboxes instead of radios, so a second
// one can be ticked beside the first. The thumb follows the CSS: left, right,
// or (both ticked) stretched across the whole track, which is the one visual
// addition and the only honest way to draw "both selected".
//
// `name` only has to be unique per switch, because each one is its own form;
// nothing is submitted, the onchange handler is the whole wiring.
function fmtSeg(name, extra){
  let h = '<div class="seg"'+(extra || '')+
    ' onclick="event.stopPropagation()">'+
    '<span class="segthumb"></span>';
  FMT_ORDER.forEach(f => {
    h += '<label class="segopt" title="'+esc(FMT_TITLE[f]||'')+'">'+
      '<input type="checkbox" name="'+esc(name)+'" value="'+f+'" '+
        'data-fmt="'+f+'"'+(fmtOn(f) ? ' checked' : '')+
        ' onchange="toggleErpFmt(this.dataset.fmt, this)">'+
      '<span class="seglab">'+esc(FMT_LABEL[f].replace(' form', ''))+
      '</span></label>';
  });
  return h + '</div>';
}

// Tick / untick one version. The LAST ticked one cannot be unticked: an empty
// choice has no file to write, and silently falling back to "full" would mean
// the next Confirm produced something the switch says is not selected.
async function toggleErpFmt(f, el){
  const cur = erpFmts();
  const on = el ? !!el.checked : cur.indexOf(f) < 0;
  let next;
  if (on){
    next = cur.indexOf(f) >= 0 ? cur.slice() : cur.concat([f]);
  } else {
    if (cur.length === 1){
      if (el) el.checked = true;      // undo the tick the browser just made
      toast('Keep at least one version selected', true);
      return;
    }
    next = cur.filter(x => x !== f);
  }
  await setErpFmts(next);
}

// ── Sold-To / Ship-To account pickers ──
// Column F and G are ERP account numbers, and which ones are offered follows
// the DOMAIN the mail came from: the Ship-To master lists, row by row, the
// (Sold-To, Ship-To) pairs that domain may order under. The list is fetched
// per domain on demand and kept for the session - the master runs to thousands
// of rows, far too much to ship with every poll.
let PARTY = {};      // domain -> {domain, sold_tos, ship_tos}
let PARTYQ = {};     // domain -> true while its request is in flight

// Drop every cached account list. The options ARE rows of the Ship-To master,
// so the moment that table is written - upload, an added or deleted row, an
// edited cell, Clear - the cache is a description of a table that no longer
// exists. Cheap: the next render fetches what it needs again.
//
// It also re-reads the IDENTITY list. A domain row added on the Customer Master
// screen changes which customer owns which domain, and `domainKnown()` reads
// that list (DATA.master) before it will draw a picker at all - so without this
// the Inbox showed the stored code as plain text and offered no Sold-To /
// Ship-To, for a domain the user had just finished adding (2026-10-27).
function forgetParty(){
  PARTY = {};
  PARTYQ = {};
  // Several cells can be pasted/tabbed through while the first refresh is in
  // flight. Mark every edit: refreshMasterList() will make another pass when
  // that happens instead of letting the first, intermediate response win.
  MASTER_DIRTY = true;
  return refreshMasterList();
}

// The customer data on its own: 4 keys, a few KB, vs ~140 KB for the whole
// dashboard. Called from forgetParty(), i.e. after every master edit.
let MASTERQ = null;
let MASTER_DIRTY = false;
function refreshMasterList(){
  if (!DATA) return Promise.resolve();
  if (MASTERQ) return MASTERQ;
  MASTERQ = (async function(){
    try {
      do {
        // An edit arriving during this await sets it back to true, which makes
        // the loop fetch the final state once more.
        MASTER_DIRTY = false;
        let r = null;
        try { r = await api('/api/master_list'); } catch (_e) {}
        if (!r || r.error) continue;
        if (r.master) DATA.master = r.master;
        if (r.erp) DATA.erp = r.erp;
        if (r.domain_status) DATA.domain_status = r.domain_status;
        if (r.ship_conflicts) DATA.ship_conflicts = r.ship_conflicts;
      } while (MASTER_DIRTY);
    } finally {
      MASTERQ = null;
      // Redraw even when the four-key identity summary is textually the same:
      // forgetParty() also cleared the detailed account cache. Without a
      // redraw, existing combo boxes survived but opened against an empty
      // PARTY object, so their Sold-To / Ship-To menus appeared blank.
      if (TAB === 'today') render();
    }
  })();
  return MASTERQ;
}

// The domain a mail row is matched by. The classifier stores it in `customer`
// (the domain IS the identity), but a mail read before the master was uploaded
// still has its own sender domain.
function rowDomain(m){
  return (m.customer || '').trim() || senderDomain(m);
}

// Whether the Ship-To master knows this domain at all. When it does not, the
// cell shows the stored code as plain text instead of an empty drop-down.
function domainKnown(c){
  const d = (c || '').trim().toLowerCase();
  return !!d && (DATA.master || []).some(
    x => x.customer.trim().toLowerCase() === d);
}

function firstTok(v){
  return String(v == null ? '' : v).split(/[,;|/]+/)[0].trim();
}

// Ask the server for the account lists of every domain in `mails` that is not
// cached yet. Returns true when something new arrived and the caller should
// render again.
//
// ONE request for the whole page (2026-10-28). This used to be a request per
// domain - twelve of them for a full Inbox, each re-reading the 2.8 MB Ship-To
// master on the server. They are also answered together, so the drop-downs all
// fill in at the same moment instead of row by row.
async function needParty(mails){
  const want = [];
  for (const m of mails){
    const c = rowDomain(m);
    if (!c || PARTY[c] || PARTYQ[c] || !domainKnown(c)) continue;
    if (want.indexOf(c) < 0) want.push(c);
  }
  if (!want.length) return false;
  want.forEach(c => { PARTYQ[c] = true; });
  let got = {};
  try {
    const r = await api('/api/party_options', {domains: want});
    got = (r && r.options) || {};
  } catch (e){
    // A failed fetch must still release the cells: they fall back to the
    // stored code as plain text, which is a readable row rather than a page
    // that sits on placeholders forever.
    got = {};
  }
  want.forEach(c => {
    PARTY[c] = got[c] || {sold_tos: [], ship_tos: []};
    delete PARTYQ[c];
  });
  patchParties(want);
  return true;
}

// ── The account picker: a searchable combo box (2026-10-28) ────────────────
// It replaced a <select> whose every candidate was an <option>. That does not
// scale: `ferguson.com` owns 2,246 Ship-To sites and `rentacenter.com` 1,861,
// so a single Inbox page carried 4,699 <option> elements and the user still had
// to scroll a 120px-wide drop-down to find one. The box is now an <input> with
// a popup that is built WHEN OPENED, filtered as you type, and capped at
// PC_MAX rows.
//
// It also accepts a number typed by hand. That is deliberate and not a hole in
// the accuracy rule: the rule ("the master decides") is about what the
// EXTRACTOR proposes, and a human typing an ERP account they were given by the
// customer is the authority on that account. An off-master value is shown amber
// and says so on hover - it is disclosed, not blocked, and never guessed.
//
// What gets SAVED is unchanged: the trimmed string in the box, posted to
// /api/update exactly as the <select> value used to be.
const PC_MAX = 50;

let PCS = {owner: null, items: [], idx: -1, q: ''};

// The candidates for one box, already narrowed by the Sold-To when this is a
// Ship-To list (`sold` is what the row's Sold-To box holds).
function pcItems(kind, domain, sold){
  const p = PARTY[domain] || {};
  const all = (kind === 'sold' ? (p.sold_tos || []) : (p.ship_tos || []));
  return kind === 'ship' && sold
    ? all.filter(s => s.sold_to === sold) : all;
}

// What one candidate says BESIDE its number. The number is what the ERP gets;
// this is what tells two numbers apart while the list is open - the ZIP for a
// site, the TYPE for a Sold-To. Display only, never written anywhere.
function pcMeta(s, kind){
  if (kind === 'sold')
    return [s.type, s.name].filter(Boolean).join(' · ');
  return [s.zip ? 'ZIP ' + s.zip : '', s.channel ? 'ch ' + s.channel : '',
          String(s.name || '')].filter(Boolean).join(' · ');
}

// The box itself. `o` = {kind, domain, sold, value, id, many, quick, title}.
// data-pkind / data-pc / data-psold are what every handler below reads, so the
// markup carries them and the popup needs nothing else.
function comboHTML(o){
  const t = o.title || FMT_PARTY_TITLE[o.kind] || '';
  return '<span class="pcombo" data-pkind="'+o.kind+'" '+
    'data-pc="'+esc(o.domain)+'" data-psold="'+esc(o.sold || '')+'" '+
    'data-pid="'+(o.id === undefined || o.id === null ? '' : o.id)+'"'+
    (o.quick ? ' data-pquick="1"' : '')+'>'+
    '<input class="pcinput'+(o.many ? ' warn' : '')+(o.off ? ' off' : '')+
      '" type="text" '+
      'autocomplete="off" spellcheck="false" data-pcval="'+
      esc(o.value || '')+'" value="'+esc(o.value || '')+'" '+
      'placeholder="'+esc(o.many ? 'several — pick one' : 'pick or type')+'" '+
      'title="'+esc(t)+'" '+
      'onfocus="pcOpen(this)" oninput="pcType(this)" '+
      'onkeydown="pcKey(event, this)" onchange="pcCommit(this)" '+
      'onblur="pcClose()">'+
    '<span class="pccaret" onmousedown="event.preventDefault();pcToggle(this)" '+
      'title="Show the account numbers">&#9660;</span></span>';
}

function pcBox(){
  let el = document.getElementById('pcmenu');
  if (!el){
    el = document.createElement('div');
    el.id = 'pcmenu';
    el.hidden = true;
    document.body.appendChild(el);
  }
  return el;
}

// Put the body-level popup beside its owner. Both the rect and the popup use
// VIEWPORT coordinates, so a horizontally scrolled Inbox card cannot move a
// Ship-To menu off screen. Reused when an async account-list fetch finishes.
function pcPlace(inp){
  if (!inp) return;
  const box = pcBox();
  const wrap = inp.closest('.pcombo') || inp;
  const r = wrap.getBoundingClientRect();
  // Wider than the cell it hangs off: the cell is ~120px and the point of the
  // popup is to read `code · ZIP · channel · site name` side by side.
  const width = Math.min(Math.max(320, Math.round(r.width)),
    Math.max(220, window.innerWidth - 12));
  box.style.width = width + 'px';
  box.style.minWidth = width + 'px';
  box.style.left = Math.round(Math.max(6,
    Math.min(r.left, window.innerWidth - width - 6))) + 'px';
  const h = box.offsetHeight;
  const below = r.bottom + 3;
  box.style.top = Math.round(below + h > window.innerHeight - 8
    ? Math.max(8, r.top - h - 3) : below) + 'px';
}

// If a master edit cleared PARTY while this already-rendered box stayed on
// screen, refill this one domain directly. The normal Inbox path still batches
// every domain through needParty(); this is only the race-safe fallback.
function pcLoad(inp){
  const wrap = inp.closest('.pcombo') || inp;
  const domain = wrap.dataset.pc;
  if (!domain || PARTY[domain] || PARTYQ[domain] || !domainKnown(domain)) return;
  PARTYQ[domain] = true;
  api('/api/party_options', {domain: domain}).then(r => {
    PARTY[domain] = (r && !r.error) ? r : {sold_tos: [], ship_tos: []};
  }).catch(() => {
    PARTY[domain] = {sold_tos: [], ship_tos: []};
  }).finally(() => {
    delete PARTYQ[domain];
    const box = pcBox();
    if (PCS.owner === inp && !box.hidden){ pcFill(inp, ''); pcPlace(inp); }
  });
}

// Open the popup under `inp`, flipping above when there is no room below.
function pcOpen(inp){
  if (!inp || inp.disabled) return;
  PCS.owner = inp;
  const box = pcBox();
  box.hidden = false;
  pcLoad(inp);
  // Opened, not typed into: show the whole list with the current value
  // highlighted. Filtering by what is already in the box would leave exactly
  // one row - the value itself - and no way to browse from there.
  pcFill(inp, '');
  pcPlace(inp);
}

function pcClose(){
  const box = document.getElementById('pcmenu');
  if (box) box.hidden = true;
}

function pcToggle(caret){
  const inp = caret.parentNode.querySelector('.pcinput');
  if (!inp || inp.disabled) return;
  const open = !pcBox().hidden && PCS.owner === inp;
  if (open){ pcClose(); return; }
  inp.focus();                       // fires onfocus -> pcOpen
  if (pcBox().hidden || PCS.owner !== inp) pcOpen(inp);
}

// Rebuild the popup for `q` (the box's text, or '' when it was merely opened):
// prefix matches first, then substring, then anything whose name / ZIP / type
// matches. Capped at PC_MAX rows; the header always says how many were found.
function pcFill(inp, q){
  const box = pcBox();
  const wrap = inp.closest('.pcombo') || inp;
  const kind = wrap.dataset.pkind;
  const domain = wrap.dataset.pc;
  const sold = wrap.dataset.psold || '';
  q = String(q === undefined ? inp.value : q).trim().toLowerCase();
  PCS.q = q;                       // what the rendered window was built for
  const all = pcItems(kind, domain, sold);
  let hits = all;
  if (q){
    const starts = [], inside = [], rest = [];
    for (const s of all){
      const c = String(s.code || '').toLowerCase();
      if (c.indexOf(q) === 0) starts.push(s);
      else if (c.indexOf(q) > 0) inside.push(s);
      else if (((s.name || '') + ' ' + (s.zip || '') + ' ' + (s.type || ''))
                 .toLowerCase().indexOf(q) >= 0) rest.push(s);
    }
    hits = starts.concat(inside, rest);
  }
  PCS.items = hits;
  const exact = hits.findIndex(s => s.code === inp.value.trim());
  PCS.idx = exact >= 0 ? exact : (hits.length ? 0 : -1);
  // The window of rows that is actually rendered. It follows the highlight, so
  // re-opening a box whose value sits at position 2,014 of 2,246 shows the
  // neighbourhood of that value instead of the first fifty numbers - the value
  // in the box has to be findable in the list it came from.
  const start = PCS.idx >= PC_MAX
    ? Math.max(0, Math.min(PCS.idx - 5, hits.length - PC_MAX)) : 0;
  const shown = hits.slice(start, start + PC_MAX);
  let h = '<div class="mphead">' + (all.length
    ? (q ? hits.length + ' of ' + all.length : all.length) +
      ' account number(s)' + (hits.length > PC_MAX ? ' — ' + PC_MAX + ' shown' : '')
    : PARTYQ[domain] ? 'loading account numbers…'
    : 'no account number on file for this customer') + '</div>';
  // Typed something the master does not carry: offer it as-is, in blue, so
  // "use what I typed" is a visible choice rather than a hidden one. Only for
  // something that could BE an account number - an ERP account is digits - so
  // a partial search like "600" does not sprout a "use 600" row above the
  // eight real matches. Written with a [0-9] class on purpose: this text goes
  // through Python's escape parser before the browser sees it, and the backslash
  // shorthand is not one of its escapes.
  const typed = inp.value.trim();
  if (q && /^[0-9]{5,}$/.test(typed) && !hits.some(s => s.code === typed))
    h += '<button type="button" class="mprow use" data-use="1" '+
      'onmousedown="event.preventDefault()" onclick="pcKeep(this)">'+
      '<b>'+esc(typed)+'</b>'+
      '<span class="mmeta">use as typed</span></button>';
  shown.forEach((s, i) => {
    const at = start + i;
    h += '<button type="button" class="mprow'+(at === PCS.idx ? ' on' : '')+
      '" data-i="'+at+'" onmousedown="event.preventDefault()" '+
      'onclick="pcPick(this)"><b>'+esc(s.code)+'</b>'+
      '<span class="mmeta">'+esc(pcMeta(s, kind))+'</span></button>';
  });
  if (!all.length)
    h += '<div class="mpfoot">Type the account number and press Enter.</div>';
  else if (!hits.length)
    h += '<div class="mpfoot">Nothing matches — Enter keeps what you typed.</div>';
  box.innerHTML = h;
  pcMark();
}

function pcMark(){
  const box = pcBox();
  box.querySelectorAll('.mprow[data-i]').forEach(b => {
    b.classList.toggle('on', +b.dataset.i === PCS.idx);
  });
  const on = box.querySelector('.mprow.on');
  if (on && on.scrollIntoView) on.scrollIntoView({block:'nearest'});
}

function pcType(inp){
  if (!PCS.owner || PCS.owner !== inp || pcBox().hidden) pcOpen(inp);
  pcFill(inp, inp.value);
}

function pcKey(ev, inp){
  const box = pcBox();
  if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp'){
    ev.preventDefault();
    if (box.hidden || PCS.owner !== inp){ pcOpen(inp); return; }
    const n = PCS.items.length;
    if (!n) return;
    const step = ev.key === 'ArrowDown' ? 1 : -1;
    const want = Math.max(0, Math.min(n - 1, PCS.idx + step));
    if (want === PCS.idx) return;
    PCS.idx = want;
    // Walking past the rendered window scrolls the window instead: the list is
    // capped at PC_MAX rows, so the highlight has to be able to leave it.
    if (box.querySelector('.mprow[data-i="' + want + '"]')){
      pcMark();
    } else {
      pcFill(inp, PCS.q);          // rebuilds around the highlight...
      PCS.idx = want;              // ...but pcFill re-derives it from the value
      pcMark();
    }
  } else if (ev.key === 'Enter'){
    ev.preventDefault();
    if (!box.hidden && PCS.idx >= 0 && PCS.items[PCS.idx]){
      pcTake(inp, PCS.items[PCS.idx].code);
    } else {
      pcClose();
      pcCommit(inp);
    }
  } else if (ev.key === 'Escape'){
    // Back to what was saved: Escape is "never mind", not "clear the field".
    ev.preventDefault();
    pcClose();
    inp.value = inp.dataset.pcval || '';
    inp.blur();
  } else if (ev.key === 'Tab'){
    pcClose();
  }
}

function pcPick(btn){
  const s = PCS.items[+btn.dataset.i];
  if (s && PCS.owner) pcTake(PCS.owner, s.code);
}

function pcKeep(btn){
  pcClose();
  pcCommit(PCS.owner);
}

function pcTake(inp, code){
  inp.value = code;
  pcClose();
  pcCommit(inp);
}

// Save what the box holds. The guard is `data-pcval` (what the field was
// rendered / last saved with), so blurring an untouched box writes nothing.
async function pcCommit(inp){
  if (!inp) return;
  const wrap = inp.closest('.pcombo') || inp;
  const v = (inp.value || '').trim();
  if (v === (inp.dataset.pcval || '')){ pcSync(inp); return; }
  inp.dataset.pcval = v;
  pcSync(inp);
  const kind = wrap.dataset.pkind;
  if (wrap.dataset.pquick){ qPartySet(kind, v); return; }
  await rowParty(wrap, +wrap.dataset.pid,
    kind === 'sold' ? 'sold_to' : 'ship_to', v);
}

// Restyle one box from its own value: amber when the number is not in this
// customer's account list, and the ZIP caption for a Ship-To.
function pcSync(inp){
  const wrap = inp.closest('.pcombo') || inp;
  const kind = wrap.dataset.pkind;
  const v = (inp.value || '').trim();
  const hit = v ? ((PARTY[wrap.dataset.pc] || {})[
    kind === 'sold' ? 'sold_tos' : 'ship_tos'] || [])
    .find(s => s.code === v) : null;
  const off = !!v && !hit;
  inp.classList.toggle('off', off);
  inp.title = off
    ? v + ' is not in this customer’s account list — it is written as typed'
    : (FMT_PARTY_TITLE[kind] || '');
  if (kind === 'ship'){
    const cap = wrap.parentNode
      ? wrap.parentNode.querySelector('[data-pzip]') : null;
    if (cap) cap.textContent = zipText(
      siteZip(wrap.dataset.pc, v, wrap.dataset.psold));
  }
  return hit;
}

// A popup pinned with `position:fixed` does not follow its cell, so it is
// closed rather than repositioned: scrolling, resizing or clicking anywhere
// else means the list is no longer about what is on screen. The capture phase
// is what catches a scroll INSIDE `.cardbody` - that container, not the window,
// is what moves the table.
document.addEventListener('mousedown', ev => {
  if (ev.target && ev.target.closest &&
      (ev.target.closest('#pcmenu') || ev.target.closest('.pcombo'))) return;
  pcClose();
}, true);
document.addEventListener('scroll', ev => {
  const box = document.getElementById('pcmenu');
  if (!box || box.hidden) return;
  if (ev.target && ev.target.closest && ev.target.closest('#pcmenu')) return;
  pcClose();
}, true);
window.addEventListener('resize', () => pcClose());

// The ZIP of the site a row currently points at, out of the customer master.
// Display only - see pcMeta().
function siteZip(domain, code, sold){
  const all = ((PARTY[domain] || {}).ship_tos || []);
  let hit = all.filter(s => s.code === code && (!sold || s.sold_to === sold));
  if (!hit.length) hit = all.filter(s => s.code === code);
  return hit.length ? String(hit[0].zip || '').trim() : '';
}

function zipText(z){ return z ? 'ZIP ' + z : ''; }

// The line under the Ship-To picker. Keeping it in its own element lets
// patchParty()/rowParty() update it without redrawing the row.
function zipCapHtml(z){
  return '<div class="pzip" data-pzip="1" title="Postal code from the '+
    'customer master — for telling sites apart. The order itself uses the ZIP '+
    'printed on the PO.">'+esc(zipText(z))+'</div>';
}

// Which account number a row starts on: the one saved to the database when the
// domain still owns it, else the single one the domain has.
function rowPick(m, kind){
  return rowPickOf(rowDomain(m), kind,
    m[kind === 'sold' ? 'sold_to' : 'ship_to'] || '');
}

// The same rule from scalars, so a cell can be rebuilt without its mail object.
function rowPickOf(domain, kind, stored){
  const p = PARTY[domain] || {};
  const codes = ((kind === 'sold' ? p.sold_tos : p.ship_tos) || [])
    .map(s => s.code);
  const st = stored || '';
  const first = firstTok(st);
  if (first && codes.indexOf(first) >= 0) return first;
  if (st && codes.indexOf(String(st).trim()) >= 0) return String(st).trim();
  if (codes.length === 1) return codes[0];
  return '';
}

function partyCell(m, kind){
  return partyCellRaw(rowDomain(m), kind,
    m[kind === 'sold' ? 'sold_to' : 'ship_to'] || '', m.sold_to || '', m.id);
}

// The cell itself, from scalars rather than a mail object, so it can be rebuilt
// later for ONE row by patchParty(). The account lists arrive a moment after
// the table is drawn; the placeholder therefore has to carry enough to
// re-render itself, or a cell born before the answer stays on "…" until the
// next full page load (60 s) - the "the Inbox will not offer Sold-To / Ship-To"
// report (2026-10-27).
function partyCellRaw(domain, kind, stored, soldStored, id){
  if (!domainKnown(domain)) return masterCell(stored);
  if (!PARTY[domain])
    return '<span class="pwait" data-pwait="'+esc(domain)+'" '+
      'data-pkind="'+kind+'" data-pstored="'+esc(stored)+'" '+
      'data-psold="'+esc(soldStored || '')+'" data-pid="'+id+'" '+
      'title="Loading the account numbers this customer owns…">'+
      dotsHTML()+'</span>';
  const cur0 = rowPickOf(domain, kind, stored);
  const sold = kind === 'ship' ? rowPickOf(domain, 'sold', soldStored) : '';
  // Several numbers on file and none chosen yet: flag it, because the ERP
  // needs exactly one of each - and the Ship-To decides column D.
  const many = stored.split(/[,;|]+/).filter(x => x.trim()).length > 1;
  // A stored number the master no longer carries still has to be VISIBLE: run
  // this row'll write it into F/G, and an empty box would say "nothing here"
  // while the order keeps its old account. It is flagged amber by `off`, and
  // the caption/tooltip says it is not in the list - never replaced silently.
  const cur = cur0 || (many ? '' : firstTok(stored));
  const allCodes = (kind === 'sold' ? ((PARTY[domain] || {}).sold_tos || [])
                                    : ((PARTY[domain] || {}).ship_tos || []));
  const off = !!cur && !allCodes.some(s => s.code === cur);
  // A domain with no account numbers still gets a box: typing the number is
  // the only way to fill F/G then, and the popup says so instead of the cell
  // being a piece of dead text.
  return comboHTML({kind: kind, domain: domain, sold: sold, value: cur,
                    id: id, many: many, off: off})+
    (kind === 'ship' ? zipCapHtml(siteZip(domain, cur, sold)) : '');
}

const FMT_PARTY_TITLE = {
  sold: 'Sold-To-Party — the ERP account number this order was placed with '+
        '(goes in column F)',
  ship: 'Ship-To-Party — the site the goods go to (goes in column G). It is '+
        'half of the key that fills N/R/W/X/AI, and its TYPE sets the '+
        'Distr. Channel in column D'
};

// The three-dot pulse that stands in for a picker whose list is still on its
// way (see the .dots-container rules). The markup is the Uiverse one: a flex
// container of three .dot spans, each on its own animation delay.
function dotsHTML(){
  return '<span class="dots-container dots-sm" role="status" '+
    'aria-label="Loading">'+
    '<span class="dot"></span><span class="dot"></span>'+
    '<span class="dot"></span></span>';
}

// Swap the loading placeholder of every cell whose domain just arrived - ONE
// pass over the document for the whole batch.
//
// There is nothing to refill in a box that was already drawn: its candidates
// are read out of PARTY when it is OPENED (pcFill), so an open list always
// reflects the cache as it stands. That is also what makes `forgetParty()`
// safe - a stale list cannot survive a master edit, because it does not exist
// until somebody opens the box.
function patchParties(domains){
  const want = {};
  domains.forEach(d => { want[d] = true; });
  document.querySelectorAll('span[data-pwait]').forEach(sp => {
    if (!want[sp.dataset.pwait]) return;
    const td = sp.closest('td');
    if (!td) return;
    td.innerHTML = partyCellRaw(sp.dataset.pwait, sp.dataset.pkind,
      sp.dataset.pstored || '', sp.dataset.psold || '', +sp.dataset.pid);
  });
  // A combo may already exist when forgetParty() clears its cache. If its
  // menu was opened during the refetch, refresh that detached body-level
  // popup too; replacing only loading placeholders would leave it blank.
  if (PCS.owner && !pcBox().hidden){
    const wrap = PCS.owner.closest('.pcombo');
    if (wrap && want[wrap.dataset.pc]){
      pcFill(PCS.owner, '');
      pcPlace(PCS.owner);
    }
  }
}

function patchParty(domain){
  patchParties([domain]);
}

// The ZIP caption under a Ship-To picker, kept in step with the selection.
// `wrap` is the .pcombo element (or anything carrying data-pc).
function setZipCap(wrap, code){
  const cap = wrap.parentNode
    ? wrap.parentNode.querySelector('[data-pzip]') : null;
  if (cap) cap.textContent = zipText(
    siteZip(wrap.dataset.pc, code, wrap.dataset.psold));
}

// Save one account number against one row. `wrap` is the .pcombo, `code` is
// what the box now holds - a number picked from the list or typed by hand, the
// two are the same thing from here on. The value is written verbatim: this is
// the human deciding an ERP account, not the extractor guessing one.
async function rowParty(wrap, id, field, code){
  const inp = wrap.querySelector ? wrap.querySelector('.pcinput') : null;
  if (inp) inp.classList.remove('warn');
  const tr = wrap.closest('tr');
  const shop = tr ? tr.querySelector('.pcombo[data-pkind="ship"]') : null;
  if (field === 'sold_to' && shop){
    // Re-narrow the Ship-To candidates, but never move the selection itself:
    // what the order ships to is not a consequence of the Sold-To.
    shop.dataset.psold = code;
    // The Ship-To list is narrowed now: if it is on screen, redraw it
    // unfiltered so the new set is what the user sees.
    if (PCS.owner && PCS.owner.closest('.pcombo') === shop) pcFill(PCS.owner, '');
    setZipCap(shop, shop.querySelector('.pcinput').value.trim());
  }
  if (field === 'ship_to') setZipCap(wrap, code);
  const r = await api('/api/update', {id: id, field: field, value: code});
  if (r && r.error){ alert(r.error); return; }
  // Column D is read off the pair's TYPE, so a change of Ship-To is the one
  // that can move the channel - say so, or the user has no way to see it.
  const ch = field === 'ship_to'
    ? partyChannel(wrap.dataset.pc, code, wrap.dataset.psold) : '';
  toast((field === 'sold_to' ? 'Sold-To-Party ' : 'Ship-To-Party ') +
    (code || 'cleared') +
    (field === 'ship_to' ? (ch ? ' · channel ' + ch
                               : ' · no channel on file') : ''));
}

// The Distribution Channel that goes in column D, for a (Sold-To, Ship-To)
// pair. It is not stored anywhere on its own: channel_for_type() derives it
// from the TYPE on that very row (Builder -> 11, anything else -> 10).
function partyChannel(domain, ship, sold){
  if (!ship) return '';
  const p = PARTY[domain] || {};
  const hit = (p.ship_tos || []).find(
    s => s.code === ship && (!sold || !s.sold_to || s.sold_to === sold))
    || (p.ship_tos || []).find(s => s.code === ship);
  return (hit && hit.channel) || '';
}

// The Ship-To master row for the site a row names. Empty when that pair has
// no row, or when the account list has not arrived.
function masterShipHit(domain, ship, sold){
  if (!ship) return null;
  const p = PARTY[domain] || {};
  return (p.ship_tos || []).find(
      s => s.code === ship && (!sold || !s.sold_to || s.sold_to === sold))
    || (p.ship_tos || []).find(s => s.code === ship)
    || null;
}

// The NAME of the site, used as the default for column N. The address is
// deliberately not read from here any more: the master holds the billing
// site, and a PO's delivery address is routinely a different place.

// ── The Ship-To block ───────────────────────────────────────────────────
// Two columns are shown every day:
//
//   N  Ship-to Name      defaults to the Ship-To master's name, editable
//   R  Ship-to Address   typed per order, no master default
//
// The other ten fields live behind a disclosure inside the address cell:
//
//   O  Ship-to Name 2      S  Ship-to Street 2
//   P  Ship-to Name 3      T  Ship-to Street 3
//   Q  Ship-to Name 4      U  Ship-to Street 4
//                         V  Ship-to Street 5
//                         W  Ship-to Postal Code
//                         X  Ship-to City
//                        AZ  Ship-to Region (a state, chosen from a list)
//
// Showing twelve inputs on every Inbox row would make the table unreadable,
// and most orders never need more than N and R. The disclosure is per row and
// is not remembered between renders - it is an inspection, not a preference.
const SHIP_MORE = [
  ['ship_to_name2',  'Name 2',           'text',   'O'],
  ['ship_to_name3',  'Name 3',           'text',   'P'],
  ['ship_to_name4',  'Name 4',           'text',   'Q'],
  ['ship_to_street2','Street 2',         'text',   'S'],
  ['ship_to_street3','Street 3',         'text',   'T'],
  ['ship_to_street4','Street 4',         'text',   'U'],
  ['ship_to_street5','Street 5',         'text',   'V'],
  ['ship_to_zip',    'Postal code',      'text',   'W'],
  ['ship_to_city',   'City',             'text',   'X'],
  ['ship_to_region', 'State / region',   'state',  'AZ'],
  // The two dates belong to the same "what this order carries" idea even
  // though they are not address fields, and they follow the same rule: type
  // here to override what the PO printed. Leave blank and the document (and,
  // for R.D.D, PO date + 6 working days) supplies them.
  ['rdd',            'R.D.D',            'date',   'K'],
  ['po_date',        'PO date',          'date',   'M'],
];

// Every field of the printed Ship-To block - N and R plus SHIP_MORE - in the
// order the ERP form prints them. Confirm sends exactly these values with its
// request: the box saves on blur, and the blur that saves it is the same click
// that starts Confirm, so the upload must not depend on which of the two
// requests the server happens to read first (see of_server._typed_ship).
const SHIP_FIELDS = ['ship_to_name', 'ship_to_address']
  .concat(SHIP_MORE.map(f => f[0]));

// Mirrors store.ORDER_FIELDS (the two per-order dates). Used to keep those two
// boxes out of the folded grid, which renders everything else in SHIP_MORE.
const ORDER_FIELDS = ['rdd', 'po_date'];

// The Ship-To states offered in AZ. Read from the Ship-To master so the codes
// in use are the ones offered; a free-text box here is where a typo that the
// ERP rejects would come from.
function shipStates(){
  return (DATA && DATA.ship_states) || [];
}

// Every on-screen row that stands for one MAIL row (usually one; one per
// attachment when the email carried several order documents). The Ship-To
// block is a mail-level column, so these rows are views of a single value and
// must never be edited one at a time.
function shipRows(id){
  return (DATA.history || []).filter(x => x.id === id)
    .concat((DATA.today || []).filter(x => x.id === id));
}

async function load(){
  DATA = await api('/api/dashboard');
  updateBadges();
  document.getElementById('meta').textContent = '';
  render();
  watchSync();
}

// The background sync poll (every 3s while a collection is running) used to
// call load() directly, which re-renders the WHOLE page from the server's
// copy of settings - including the Mail Source form. A user picking a
// mailbox from the dropdown while the startup auto-collect was still running
// would see their choice silently reverted before they could click Save,
// and Outlook would then be read from whatever mailbox was saved before.
// This refreshes the sync banner and badges the same way, but leaves the
// Settings (and Codes, matching the slower poll below) screen alone.
async function pollDuringSync(){
  DATA = await api('/api/dashboard');
  updateBadges();
  watchSync();
  if (TAB !== 'settings' && TAB !== 'codes') render();
}

// Show a banner while background collection runs, then auto-refresh when it finishes
function watchSync(){
  const st = (DATA && DATA.sync_status) || {};
  let bar = document.getElementById('syncbar');
  if (st.running){
    if (!bar){
      bar = document.createElement('div');
      bar.id = 'syncbar';
      bar.className = 'syncbar';
      document.body.appendChild(bar);
    }
    bar.innerHTML = '<span class="spin"></span> '+
      esc(st.phase || 'Collecting emails…')+
      ' <span class="muted">— the dashboard stays usable</span>';
    if (!SYNCPOLL) SYNCPOLL = setInterval(pollDuringSync, 3000);
  } else {
    if (bar) bar.remove();
    if (SYNCPOLL){ clearInterval(SYNCPOLL); SYNCPOLL = null;
      if (st.error) alert('Sync failed: '+st.error);
      else if (st.new) toast(st.new+' new email(s) collected');
    }
  }
}

function fmtClock(iso){
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const today = d.toDateString() === new Date().toDateString();
  return (today ? '' : d.toLocaleDateString('en-US',
      {month:'short', day:'numeric'}) + ' ') +
    d.toLocaleTimeString('en-US', {hour:'numeric', minute:'2-digit'});
}

function renderSyncBox(){
  const box = document.getElementById('syncbox');
  if (!box || !DATA) return;
  const s = DATA.sync_state || {};
  const cfg = (DATA.settings || {}).sync || {};
  let sched;
  if (cfg.mode === 'off') sched = 'Auto sync off';
  else if (cfg.mode === 'times')
    sched = 'Daily at ' + (cfg.times || []).join(', ');
  else sched = 'Every ' + (cfg.interval_min || 60) + ' min';

  box.innerHTML =
    '<div class="syncrow"><span class="dot '+
      (s.running ? 'blue' : (s.last_error ? 'red' : 'green'))+'"></span>'+
      '<b>'+(s.running ? 'Syncing…' : 'Sync')+'</b></div>'+
    '<div class="syncline">Last: '+esc(fmtClock(
      DATA.last_collected || s.last_finished))+'</div>'+
    '<div class="syncline">Next: '+esc(cfg.mode === 'off' ? '—' :
      fmtClock(s.next_due))+'</div>'+
    '<div class="syncline muted">'+esc(sched)+'</div>'+
    (s.last_error ? '<div class="syncline err">'+
      esc(s.last_error.slice(0,60))+'</div>' : '')+
    '<button class="btn syncbtn" onclick="syncNow()"'+
      (s.running ? ' disabled' : '')+'>Sync now</button>';
}

async function syncNow(){
  toast('Collecting…');
  const r = await api('/api/collect', {});
  if (r.error){ alert(r.error); return; }
  toast(r.message ? r.message.split('\\n')[0] : 'Sync done');
  await load();
}

function updateBadges(){
  if (!DATA) return;
  // Based on the selected date (so totals match the summary strip)
  const onDay = a => (a||[]).filter(
    m => (m.received_at||'').slice(0,10) === SELDATE).length;
  setBadge('b-master', DATA.unclassified.length);   // not-in-master is date-independent
  setBadge('b-notmypo', onDay(DATA.excluded));
  // Completed and Order Upload are one screen now: the badge counts the whole
  // day's confirmed POs, and the screen shows which still need uploading.
  setBadge('b-completed', onDay(
    DATA.history.filter(m => m.status === 'Done')));
}

function setBadge(id, n){
  const el = document.getElementById(id);
  el.textContent = n;
  el.classList.toggle('zero', n === 0);
}

// Everything the request needs to describe the order as it stands ON SCREEN.
//
// The row's inputs save themselves on blur, and this click is what blurs them,
// so the save and the action race. The account numbers and the ship block are
// read here and sent WITH the action instead, so the file can only ever be
// built from what the user was looking at.
function rowSnapshot(id, index){
  const mine = shipRows(id);
  const row = mine.find(x => (index === undefined || index === null)
                             ? true : x.att_index === index) || mine[0];
  const out = {};
  if (!row) return out;
  const ship = {};
  SHIP_FIELDS.forEach(f => { ship[f] = (row[f] || '').trim(); });
  out.ship = ship;
  // The pickers DISPLAY a value the page derives from the master and only save
  // it when the user changes it, so a row that arrived with one account on file
  // showed F and G but had nothing in the database - which is why Confirm used
  // to produce a file with columns F, G and D empty.
  out.sold_to = rowPick(row, 'sold');
  out.ship_to = rowPick(row, 'ship');
  return out;
}

async function act(id, action, index){
  // Confirm no longer writes a file: it opens the READING, in the Read tab,
  // and the format is chosen on the page that follows (2026-10-28). Reject and
  // the rest are untouched.
  if (action === 'confirm') return startReading(id, index);
  toast('Updating…', false);
  const r = await api('/api/action', {id: id, action: action,
    index: (index === undefined || index === null) ? undefined : index});
  if (r.message) alert(r.message);
  await load();
}

// The preview's button. The reading was already paid for by startReading(), so
// the server rebuilds from its cache (force=False) - this is file writing, not
// another API call.
async function generateOrder(id, index, fmts){
  const want = normFmts(fmts);
  toast(want.length > 1 ? 'Writing '+want.length+' Order Upload files…'
                        : 'Writing the Order Upload file…', true);
  // Remember the choice the user made on the preview, but do not go through
  // setErpFmts(): that re-renders the page we are about to leave.
  if (want.join() !== erpFmts().join()){
    ERPFMTS = want;
    api('/api/erp_format', {formats: want}).then(r => {
      ERPFMTS = null;
      if (r && r.formats && DATA) DATA.erp_formats = r.formats;
    });
  }
  const body = {id:id, action:'confirm'};
  if (index !== undefined && index !== null) body.index = index;
  body.format = want;
  const snap = rowSnapshot(id, index);
  body.sold_to = snap.sold_to;
  body.ship_to = snap.ship_to;
  // The ship block comes from the PREVIEW's boxes - they are what the user is
  // looking at when they press the button. The row only supplies it when the
  // preview was opened some other way.
  body.ship = Object.assign({}, (PREVIEW && PREVIEW.typed) || snap.ship || {});
  const r = await api('/api/action', body);
  hideToast();
  if (r.error){ alert(r.error); return; }   // still on the preview, can retry
  // Done → the OUTPUT tab, with the file(s) in a banner above the list the row
  // has just joined. This is the whole point of the three-tab pipeline: the
  // artifact and the register of artifacts are the same screen.
  PREVIEW = null;
  const made = (r.files || []).filter(f => f && f.url);
  LASTFILES = made.length ? {files: made}
    : (r.url ? {files: [{fmt: want[0], name: r.name || 'Order Upload',
                         url: r.url}]} : null);
  ITAB = 3;
  MAILPAGE = 0;
  render();
  await load();
  if (r.message) alert(r.message);
}

// ── The reading, then the preview ────────────────────────────────
// Shown in the READ tab, in that order: the radar while the document is being
// read, then every per-order column it produced plus the format choice. It
// lists only the per-order columns - the fixed constants (Sales Org 3101,
// Division 00, USD) are the same on every line, and Material / Quantity / Unit
// Price are reviewed line by line on the Quick Convert card afterwards.
let PREVIEW = null;   // {id, index, reading:true} then the server payload
let PREVIEW_SEQ = 0;  // bumps on every open/close, to drop stale answers

// Extract. The reading happens HERE (server side), because the delivery address
// and the two dates are printed on the PO - a preview that skipped the reading
// could not show the very columns it exists to confirm.
//
// It lands in the READ tab rather than a step of its own (2026-10-28): that tab
// is where a reading lives, so the in-flight panel, the preview and the
// register are three states of ONE screen instead of three screens.
//
// And the preview is a PAGE, not a dialog (2026-10-23). As a floating box its
// address block and its format buttons sat below the fold on a laptop, which is
// how a preview that HAD the address gets reported as having none.
async function startReading(id, index){
  const snap = rowSnapshot(id, index);
  const body = {id: id, format: erpFmts()};
  if (index !== undefined && index !== null) body.index = index;
  Object.assign(body, snap);
  const seq = ++PREVIEW_SEQ;
  READING = {id: id, index: index};
  PREVIEW = null;
  LASTFILES = null;              // a new order: the last banner is history
  // Move to the Read tab BEFORE the request: the panel it shows is the honest
  // answer to "what is happening", and the reading is what that tab is about.
  ITAB = 2;
  MAILPAGE = 0;
  render();
  loadReads();
  const r = await api('/api/order_preview', body);
  // The user walked away (Cancel, another row, another tab) while this was in
  // flight: the answer is for a PO they are no longer looking at, so drop it.
  if (seq !== PREVIEW_SEQ) return;
  READING = null;
  if (r.error){
    alert(r.error);
    render();               // back to the register, nothing left in flight
    return;
  }
  // The ship block is editable HERE from now on (its per-row boxes are gone).
  // Seed it from whatever the row still holds, so an override typed earlier -
  // or by an older version - is not silently dropped.
  PREVIEW = Object.assign({id: id, index: index, fmts: erpFmts(),
                           typed: Object.assign({}, snap.ship || {})}, r);
  render();
}

// Step 2's body. An indeterminate indicator, on purpose: the API answers once,
// at the end, and there is no progress to report. A radar sweep and a bouncing
// dot say "working" without inventing a percentage that would sit at 30% for a
// minute and then jump to 100.
function readingPanel(){
  // Everything this panel used to say under the spinner is in the head marker:
  // while a read is running there is nothing to act on, so the paragraphs were
  // three lines of text the user had already decided to wait for.
  return '<div class="flowpage">'+
    '<div class="flowhead"><h3>Reading the PO…'+faq('flowread')+'</h3></div>'+
    '<div class="flowbody" style="padding-bottom:18px">'+
    '<div class="reading">'+
      '<div class="radar"><i></i></div>'+
      '<div class="rtxt"><div class="rtitle">Extracting the order '+
        '<span class="dots"><b></b><b></b><b></b></span></div>'+
      '</div>'+
    '</div>'+
    '</div><div class="flowfoot">'+
      '<button class="btn" onclick="cancelReading()">Cancel</button>'+
    '</div></div>';
}

// What the file will contain, and which file(s) to write.
//
// The format choice is at the TOP: it is what this page is for. It used to be a
// row of buttons at the bottom of the dialog - below the address, below the
// notes, off the bottom of the screen.
//
// The cards are unchanged in shape (2026-10-27); they are just switchable
// independently now, so both can be lit and two files are written.
function previewPanel(){
  const rows = PREVIEW.rows || [];
  const st = PREVIEW.stats || {};
  const fmts = previewFmts();
  const byField = {};
  rows.forEach(r => { byField[r.field] = r; });

  // Grouped the way a person checks an order: who and where, then when.
  const GROUPS = [
    ['Order', ['po', 'sold_to', 'ship_to', 'distr_channel']],
    ['Delivery address', ['ship_to_name', 'ship_to_address', 'ship_to_street2',
      'ship_to_street3', 'ship_to_street4', 'ship_to_street5', 'ship_to_zip',
      'ship_to_city', 'ship_to_region']],
    ['Dates', ['rdd', 'po_date']]
  ];
  // The continuation street lines appear only when they carry something: four
  // "not printed on the PO" rows would push the real address up the page.
  const OPTIONAL = ['ship_to_street2', 'ship_to_street3', 'ship_to_street4',
                    'ship_to_street5'];

  let h = '<div class="flowpage">'+
    '<div class="flowhead"><h3>Check the order before generating'+
      faq('pvfixed')+'</h3>'+
      '<span class="spacer" style="flex:1"></span>'+
      '<button class="linkbtn" onclick="cancelReading()" '+
        'title="Cancel">&#10005;</button></div>'+
    '<div class="flowbody">';

  // 1. the decision, first
  h += '<div class="fhint" style="margin:0 0 7px; font-weight:600; '+
    'color:var(--text)">Output file'+(fmts.length > 1 ? 's' : '')+
    ' <span class="muted" style="font-weight:400">— pick one or both</span>'+
    '</div><div class="fmtpick">';
  FMT_ORDER.forEach(f => {
    h += '<button class="fmtopt'+(fmts.indexOf(f) >= 0 ? ' on' : '')+'" '+
      'data-f="'+f+'" onclick="togglePreviewFmt(this.dataset.f)" '+
      'title="'+esc(FMT_TITLE[f] || '')+'">'+
      '<span class="fmk"></span>'+
      '<b>'+esc(FMT_LABEL[f])+'</b>'+
      '<span class="fmo">'+esc(FMT_SHORT[f] || '')+'</span></button>';
  });
  h += '</div>';

  // 2. what the reading produced, as counts only. The codes themselves are not
  //    shown here - they are corrected line by line on Quick Convert.
  if (st.lines !== undefined)
    h += '<p class="pvnote" style="margin:0 0 12px; color:var(--text)">'+
      '<b>'+st.codes+' line(s)</b> read from the document'+
      (st.needs_review
        ? ', <b style="color:var(--amber)">'+st.needs_review+'</b> with a code '+
          'that is not in the Material Code list - those are shown unticked '+
          'on Quick Convert and are not written until you tick them'
        : '')+'.</p>';

  // 2b. more than one order: ONE row per PO. The column table below can show
  //     only one delivery address and one set of dates, so when the document
  //     holds four POs the honest thing is to list all four and let the table
  //     say "each PO has its own" - which is also what the file will contain.
  const ords = PREVIEW.orders || [];
  if (ords.length > 1)
    h += '<div class="ordbox"><div class="ordhead">'+ords.length+
      ' separate POs in this document</div>'+orderTable(ords)+'</div>';

  // 3. the header block, two columns. The address / name / date fields are
  //    INPUTS: this page is where an override is typed now, and what is in these
  //    boxes is what Generate writes. A blank box means "use what the PO
  //    printed", which is why the document's value sits in the placeholder.
  const typed = PREVIEW.typed || {};
  h += '<div class="pvpage">';
  GROUPS.forEach(g => {
    let cells = '';
    g[1].forEach(f => {
      const r = byField[f];
      if (!r) return;
      const mine = String(typed[f] || '').trim();
      if (OPTIONAL.indexOf(f) >= 0 && !r.value && !mine) return;
      const editable = SHIP_FIELDS.indexOf(f) >= 0;
      const pend = !r.value && !mine;
      const src = mine ? 'typed here' : (r.source || '');
      cells += '<div class="pvf"><span class="l">'+esc(r.letter)+'</span>'+
        '<span class="h">'+esc(r.header)+'</span>'+
        '<span class="v'+(pend ? ' pending' : '')+'">'+
          (editable
            ? '<input class="pvin" data-pvfield="'+f+'" value="'+esc(mine)+'" '+
              'placeholder="'+esc(r.value || r.pending || '')+'" '+
              'title="Type to override what the PO printed. Blank means '+
              'use the value printed on the PO." '+
              'oninput="pvShip(this.dataset.pvfield, this.value)">'
            : (pend ? esc(r.pending || 'empty') : esc(r.value)))+
        '</span>'+
        (src && !pend ? '<span class="s">'+esc(src)+'</span>' : '')+
        '</div>';
    });
    if (cells) h += '<div class="pvgroup">'+esc(g[0])+'</div>'+cells;
  });
  h += '</div>';

  (PREVIEW.warnings || []).forEach(w => {
    h += '<p class="pvnote" style="color:var(--amber)">&#9888; '+esc(w)+'</p>';
  });

  const ch = PREVIEW.channel;
  h += '</div><div class="flowfoot">'+
    '<span class="muted" style="font-size:12px">'+
      (ch ? 'Distr. Channel '+esc(ch) : 'No channel on file')+'</span>'+
    '<span class="spacer" style="flex:1"></span>'+
    '<button class="btn" onclick="cancelReading()">Cancel</button>'+
    // The destination is part of the label: the button both writes the file and
    // moves to the tab that lists it, and a bare "Generate" left people looking
    // for where it went (2026-10-28).
    '<button class="btn primary" onclick="confirmPreview()" '+
      'title="Write the file(s) and open Output">'+
      'Generate '+(fmts.length > 1 ? fmts.length+' files'
                                   : esc(FMT_LABEL[fmts[0]] || ''))+
      ' &#8594; Output</button>'+
    '</div></div>';
  return h;
}

// What step 3 has ticked. PREVIEW.fmts is the page's own working copy; until
// the user touches a card it is whatever the machine's saved choice is, so the
// preview opens showing the same thing the switch says.
function previewFmts(){
  return normFmts((PREVIEW && PREVIEW.fmts) || erpFmts());
}

// Typing must NOT re-render: the page would be rebuilt on every keystroke and
// the caret would jump. The box keeps its own value; PREVIEW.typed is what
// Generate sends.
function pvShip(field, value){
  if (!PREVIEW) return;
  PREVIEW.typed = PREVIEW.typed || {};
  const v = String(value || '').trim();
  if (v) PREVIEW.typed[field] = v;
  else delete PREVIEW.typed[field];   // blank = fall back to the PO's value
}

// Tick / untick one of the two cards. Same rule as the switch: the last one
// lit stays lit, because an empty choice has no file to write.
function togglePreviewFmt(f){
  if (!PREVIEW) return;
  const cur = previewFmts();
  if (cur.indexOf(f) >= 0){
    if (cur.length === 1){
      toast('Keep at least one version selected', true);
      return;
    }
    PREVIEW.fmts = cur.filter(x => x !== f);
  } else {
    PREVIEW.fmts = cur.concat([f]);
  }
  render();
}

function confirmPreview(){
  if (!PREVIEW) return;
  const job = {id: PREVIEW.id, index: PREVIEW.index, fmts: previewFmts()};
  // The page is NOT dismissed first: if the file cannot be written, the user is
  // still on step 3 with the columns in front of them and can press again.
  generateOrder(job.id, job.index, job.fmts);
}

function masterFor(customer){
  const c = (customer || '').trim().toLowerCase();
  if (!c) return null;
  return (DATA.master || []).find(
    m => m.customer.trim().toLowerCase() === c);
}

// A customer is identified by the DOMAIN of the sender address, so there is no
// per-member lookup any more: everything a mail row needs (Role, Sold-To,
// Ship-To) sits on the customer. See classifier.match_customer().
function senderDomain(m){
  const s = (m.sender || '').trim().toLowerCase();
  const i = s.lastIndexOf('@');
  return (i >= 0 ? s.slice(i + 1) : (m.sender_domain || '')).trim();
}

function seqBadge(m){
  // Mark rows split into individual orders because of multiple attachments
  if (!m.att_total || m.att_total < 2) return '';
  return '<span class="seqb" title="Separate order '+m.att_seq+' of '+
    m.att_total+' from this email">'+m.att_seq+'/'+m.att_total+'</span>';
}

// Mails with 2 or more order documents are split into one order row per
// document. Each row keeps its own state (status/confirmed_at/erp_file) in
// att_states[index].
//
// The list of order documents comes from the server (m.att_docs), never from a
// local filter. The page used to narrow to ".pdf" here while the server
// narrowed to ".pdf/.xlsx/.xlsm/.xls/.csv" and /api/open filtered not at all,
// so for [quote.xlsx, order.pdf] the row on screen and the file the server
// confirmed were different attachments.
function expandOrders(mails){
  const out = [];
  for (const m of mails){
    const docs = m.att_docs || [];
    if (docs.length < 2){ out.push(m); continue; }
    docs.forEach((d, n) => {
      // d.i is the index in the STORED path list, which is what att_states is
      // keyed by - not the position in this narrowed list.
      const st = (m.att_states || {})[String(d.i)] || {};
      out.push(Object.assign({}, m, {
        att_index: d.i, att_seq: n + 1, att_total: docs.length,
        pdf_paths: [m.pdf_paths[d.i]],
        // Keep this row's own document, WITH its stored index, so the
        // attachment link opens the file this row is about.
        att_docs: [d],
        status: st.status || 'Not yet',
        confirmed_at: st.confirmed_at || '',
        erp_file: st.erp_file || '',
        erp_file2: st.erp_file2 || '',
        note: st.note || '',
        erp_uploaded: st.erp_uploaded || 0,
        po_number: st.po_number || m.po_number,
      }));
    });
  }
  return out;
}

function actIdx(m, action){
  return 'act(' + m.id + ',\\'' + action + '\\'' +
    (m.att_index === undefined ? '' : ',' + m.att_index) + ')';
}

function masterCell(text){
  const t = text && text.length ? text : '—';
  return '<span class="ell muted" title="'+esc(t)+'">'+esc(t)+'</span>';
}

function effStatus(m){
  // Done / Rejected are set by the user; otherwise derived from age:
  // received today -> Not yet (blue), older and untouched -> Pending (yellow)
  if (m.status === 'Done' || m.status === 'Rejected') return m.status;
  const d = (m.received_at||'').slice(0,10);
  return (d && d < localToday()) ? 'Pending' : 'Not yet';
}

function statusDot(m){
  const s = effStatus(m);
  const cls = {'Done':'green','Rejected':'red','Pending':'yellow',
    'Not yet':'blue'}[s];
  return '<span class="st"><i class="dot '+cls+'"></i>'+esc(s)+'</span>';
}

function attCell(m){
  const parts = [];
  // Use the server's list (index + name) rather than re-deriving it from
  // pdf_paths, so the index in the onclick is the stored index /api/open
  // expects. m.att_docs carries one entry on a split row, every document on
  // an unsplit one.
  let docs = m.att_docs;
  if (!docs){
    // Defensive: a page served by an older process has no att_docs. Fall back
    // to every stored path, which keeps the STORED index - the same space
    // /api/open uses - instead of the narrowed one that caused the mismatch.
    docs = (m.pdf_paths || []).map((p, i) => ({
      i: i, name: String(p).split(/[\\\\/]/).pop().replace(/^[0-9a-f]{8}_/, '')
    }));
  }
  for (const d of docs){
    parts.push('<span class="ell"><a href="#" class="attlink" title="'+esc(d.name)+'" '+
      'onclick="openFile('+m.id+','+d.i+');return false">&#128196; '+esc(d.name)+'</a></span>');
  }
  if (parts.length) return parts.join('');
  // Only report unsaved 'document' attachments. Signature/logo images are never
  // saved in the first place, so they are not warned about.
  const DOC = /\\.(pdf|xlsx?|xlsm|csv|tsv|txt|docx?|zip|xml|edi)$/i;
  const names = (m.attachments || []).filter(n => n && DOC.test(n));
  if (names.length)
    return '<span class="ell" title="'+esc(names.join('; '))+
      ' — not saved yet. Click to fetch it from Outlook.">'+
      '<a href="#" class="attmiss" onclick="refetchAtt('+m.id+
      ');return false">&#9888; '+esc(names[0])+
      (names.length>1 ? ' +'+(names.length-1) : '')+'</a></span>';
  return '<span class="muted">—</span>';
}

function toast(msg, sticky){
  // sticky: stays up until hideToast() is called, instead of auto-hiding
  // after a fixed 2s. Used for actions (like Confirm/extraction) whose real
  // duration is unknown and can be much longer than a fixed timeout - a
  // toast that vanishes on its own while the work is still running makes
  // the app look frozen or done when it is neither.
  let t = document.getElementById('toast');
  if (!t){
    t = document.createElement('div');
    t.id = 'toast';
    document.body.appendChild(t);
  }
  if (t._hideTimer){ clearTimeout(t._hideTimer); t._hideTimer = null; }
  t.innerHTML = sticky
    ? '<span class="spin" style="border-color:rgba(255,255,255,.35);'+
      'border-top-color:#fff;vertical-align:middle;margin-right:7px">'+
      '</span>'+esc(msg)
    : esc(msg);
  t.classList.add('show');
  if (!sticky) t._hideTimer = setTimeout(() => t.classList.remove('show'), 2000);
}

function hideToast(){
  const t = document.getElementById('toast');
  if (t){
    if (t._hideTimer){ clearTimeout(t._hideTimer); t._hideTimer = null; }
    t.classList.remove('show');
  }
}

async function openFile(id, i){
  toast('Opening attachment…');
  const r = await api('/api/open', {id:id, index:i});
  if (r.error) alert(r.error);
}

async function refetchAtt(id){
  toast('Fetching attachment from Outlook…');
  const r = await api('/api/refetch_att', {id:id});
  if (r.error){ alert(r.error); return; }
  toast(r.count+' attachment(s) saved');
  await load();
}

async function openMail(id){
  toast('Opening email…');
  const r = await api('/api/openmail', {id:id});
  if (r.error) alert(r.error);
}

// Moving between lists updates the screen first (instant feedback); the server save follows.
function moveLocal(id, from, to){
  const src = DATA[from] || [], dst = DATA[to] || [];
  const i = src.findIndex(m => m.id === id);
  if (i < 0) return false;
  dst.push(src.splice(i, 1)[0]);
  return true;
}

async function tossPO(id, val){
  const moved = val
    ? moveLocal(id, 'history', 'excluded')
    : moveLocal(id, 'excluded', 'history');
  if (moved){ updateBadges(); render(); }
  const r = await api('/api/update',
    {id:id, field:'excluded', value:val});
  if (r && r.error){ alert(r.error); await load(); }
}


function dayNote(all, mails, label){
  const others = all.length - mails.length;
  return others
    ? '<div class="cardnote" style="background:#fffbeb; border:1px solid '+
      'var(--border); border-radius:var(--radius); margin-bottom:16px">'+
      others+' more '+label+' on other dates. Change the date in the '+
      'sidebar to see them.</div>' : '';
}

function renderNotMyPO(){
  const all = DATA.excluded || [];
  const mails = all.filter(
    m => (m.received_at||'').slice(0,10) === SELDATE);
  const note = dayNote(all, mails, 'tossed email(s)');
  if (!mails.length)
    return note + '<div class="empty">Nothing discarded on '+fmtDate(SELDATE)+
      '. Use the red <b>Discard</b> button in Inbox for emails that are not a '+
      'PO for this desk.</div>';
  let h = note + '<div class="card"><div class="cardbody">';
  h += '<table><tr><th>Status</th><th>Received</th><th>Sender</th><th>Subject</th>'+
       '<th>Attachments</th><th></th></tr>';
  for (const m of mails){
    h += '<tr><td><span class="st"><i class="dot gray"></i>Not a PO</span></td>'+
      '<td class="muted">'+fmtDT(m.received_at)+'</td>'+
      '<td class="ell" title="'+esc(m.sender)+'">'+esc(m.sender)+'</td>'+
      '<td class="ell" title="'+esc(m.subject)+'">'+
        '<a href="#" class="subjlink" '+
        'onclick="openMail('+m.id+');return false">'+esc(m.subject)+'</a></td>'+
      '<td class="muted">'+esc(m.attachments.join('; '))+'</td>'+
      '<td><button class="btn" onclick="tossPO('+m.id+',0)">Rescue</button></td>'+
      '</tr>';
  }
  return h + '</table></div></div>';
}

function groupBy(arr, keyFn){
  const g = {};
  for (const x of arr){ const k = keyFn(x); (g[k] = g[k] || []).push(x); }
  return g;
}

// Hide secondary columns depending on screen width (key columns always stay visible)
function tableSpace(){
  // The menu is no longer flush against the window: it eats its own width plus
  // the page inset on its left and the flex gap on its right. Both come from
  // CSS variables, so they are read here instead of hard-coded - a stale 240/32
  // would start hiding columns at the wrong window width and nothing would say so.
  const sb = document.querySelector('.sidebar');
  const shown = !!sb && sb.offsetParent !== null;
  let rail;
  if (shown){
    const cs = getComputedStyle(document.querySelector('.layout'));
    const gut = parseFloat(cs.paddingLeft) || 0;
    const gap = parseFloat(cs.columnGap || cs.gap) || 0;
    rail = (sb.offsetWidth || 240) + gut + gap;
  } else {
    // Railed: the island is gone but the page inset still applies on both sides
    rail = (parseFloat(getComputedStyle(document.querySelector('.layout'))
      .paddingLeft) || 0) * 2;
  }
  return Math.max(320, window.innerWidth - rail - 90);
}
function colsFor(){
  const w = tableSpace();
  return {sender: w >= 1180, role: w >= 1020, party: w >= 880};
}

function poTable(mails, opts){
  opts = opts || {};
  const C = colsFor();
  // Column widths, re-tuned 2026-10-23. The old set summed to 1322px against a
  // table floor of 1290 inside a content column capped at 1400 - 64, so the
  // Inbox was already scrolling at full screen before any window width helped.
  // These sum to ~1178 with every optional column on, which fits a maximised
  // window on a 1600-wide display with room to spare; `min-width` on the table
  // (of_erp table.fixed) matches, so the columns grow with the window instead
  // of being pinned.
  // Widths, 2026-10-23 (second pass). PERCENTAGES, summing to 100.
  //
  // The subject column used to carry a min-width on its <col>. That is not a
  // property a <col> honours - and under `table-layout:fixed` the column with no
  // width is the AUTO one that absorbs everything left over. So the subject
  // was the ONLY flexible column in the table: on a maximised window it grew past
  // 500px while every other column stayed put, and the list read as "subject,
  // with some columns attached".
  //
  // Percentages make the table scale as a whole instead of one column hoovering
  // up the surplus: 18% of the table is ~215px at the 1198px floor and ~287px on
  // a 1600-wide screen - bounded, and still the widest column.
  //
  // These are the old pixel widths divided by 1198, rebalanced on 2026-10-23
  // when three columns left the table: the PO #, and the Ship-to Name / Address
  // boxes whose editing moved to the preview page. Their 19.5% went to the
  // columns that actually need reading (customer, sender, subject) and to the
  // Action column, which has to hold two buttons (~150px at the 1198 floor).
  let h = '<table class="fixed"><colgroup>'+
    '<col style="width:6%"><col style="width:6%">'+
    (opts.showCustomer?'<col style="width:12%">':'')+
    (C.sender?'<col style="width:13%">':'')+'<col style="width:23.5%">'+
    '<col style="width:8%">'+
    (C.role?'<col style="width:4%">':'')+
    (C.party?'<col style="width:7.5%"><col style="width:7.5%">':'')+
    '<col style="width:12.5%"></colgroup>'+
    '<tr><th>Status <span class="help">?'+
    '<span class="helptip">'+
    '<span class="st"><i class="dot blue"></i>Not yet</span> received today, not processed<br>'+
    '<span class="st"><i class="dot yellow"></i>Pending</span> unprocessed since a previous day<br>'+
    '<span class="st"><i class="dot green"></i>Done</span> confirmed (Material Codes extracted)<br>'+
    '<span class="st"><i class="dot red"></i>Rejected</span> rejected / cancelled'+
    '</span></span></th><th>Received</th>';
  if (opts.showCustomer) h += '<th>Customer</th>';
  if (C.sender) h += '<th>Sender</th>';
  // The PO # column is gone: the number is in the subject line of the mail, in
  // the row's tooltip and on the preview page, and a column of it cost width
  // that the subject and the senders needed. Nor is there a Ship-to Name /
  // Address column any more - those are typed on the preview now.
  h += '<th>Subject</th><th>Attachments</th>'+
       (C.role?'<th>Role</th>':'')+
       (C.party?'<th>Sold-To-Party</th><th>Ship-To-Party</th>':'')+
       '<th>Actions</th></tr>';
  mails.forEach(m => {
    const mst = masterFor(m.customer) || {role: ''};
    // The Role is a property of the domain (Builder only when every row of it
    // is a Builder - the ERP column reads each row's own TYPE).
    const role = m.retail_builder || mst.role || '';
    // The account numbers are picked per row now: a domain can own hundreds of
    // sites, so there is no sensible list to fall back to.
    const ship = m.ship_to || '';
    const sold = m.sold_to || '';
    // Two different warnings, drawn differently. A real re-receipt (kind
    // 'repeat') is the amber row + red glyph. A first receipt whose subject
    // merely says REV/UPDATE/수정 (kind 'keyword') is a hint, not a duplicate:
    // it gets its own marker and does NOT turn the row amber, so the strong
    // signal keeps meaning something.
    const dup = m.is_duplicate
      ? ' <span class="dupflag" title="'+esc(m.dup_reason)+'">&#9888;</span>'
      : (m.dup_kind === 'keyword'
         ? ' <span class="duphint" title="'+esc(m.dup_reason)+'">&#9432;</span>'
         : '');
    // For the 2nd and later rows split from the same mail, blank the shared info (received/sender/subject)
    const cont = m.att_seq && m.att_seq > 1;
    const hid = [];
    if (!C.sender) hid.push('From: '+m.sender);
    if (!C.role && role) hid.push('Role: '+role);
    if (!C.party){ if (sold) hid.push('Sold-to: '+sold);
                   if (ship) hid.push('Ship-to: '+ship); }
    h += '<tr'+(m.is_duplicate?' class="warnrow"':'')+
        (cont?' class="controw"':'')+
        (hid.length?' title="'+esc(hid.join('\\n'))+'"':'')+'>'+
      '<td>'+statusDot(m)+'</td>'+
      '<td>'+(cont ? '' : fmtDT2(m.received_at))+'</td>'+
      (opts.showCustomer?'<td class="ell" title="'+esc(dispName(m))+'">'+
        (cont ? '' : esc(dispName(m)))+'</td>':'')+
      (C.sender ? '<td class="ell" title="'+esc(m.sender)+'">'+
        (cont ? '' : esc(m.sender))+'</td>' : '')+
      '<td class="ell" title="'+esc(m.subject)+'">'+
        (cont ? '' : '<a href="#" class="subjlink" title="Open email" '+
         'onclick="openMail('+m.id+');return false">'+esc(m.subject)+
         '</a>'+dup)+'</td>'+
      '<td>'+seqBadge(m)+attCell(m)+'</td>'+
      (C.role ? '<td>'+masterCell(role)+'</td>' : '')+
      (C.party ? '<td class="ptd">'+partyCell(m, 'sold')+'</td>'+
                 '<td class="ptd">'+partyCell(m, 'ship')+'</td>' : '')+
      // The two actions a row actually has, as words rather than glyphs: the
      // old pair of ✓ / ✕ said nothing about what either one would do, and the
      // trash icon in the first cell was a THIRD way to say "no".
      //
      // Blue = extract this order (opens the preview, step 2 of the flow).
      // Red  = discard it: it leaves the PO counts and lands on Discarded,
      //        where Rescue puts it back. Nothing here is destructive.
      '<td class="acts">'+
        '<button class="tbtn blue" title="Extract this order — reads the PO, '+
          'opens it in Read to check and pick the version, then Generate '+
          'writes the Order Upload file" '+
          'onclick="'+actIdx(m,'confirm')+'">Extract</button>'+
        '<button class="tbtn red" title="Not a PO for this desk — moves it to '+
          'Discarded, where Rescue brings it back" '+
          'onclick="tossPO('+m.id+',1)">Discard</button>'+
      '</td>'+
    '</tr>';
  });
  return h + '</table>';
}

// Customers ticked in the Inbox filter. A LIST, not one value: a desk
// compares two or three customers at a time, and re-picking one at a time to
// see the next was the whole cost of the old single-select (2026-10-27).
let CUSTPICK = [];
let CUSTOPEN = false;  // is the tick panel open? survives the re-render
let SORTASC = true;   // default: earliest received on top
let MAILQ = '';       // free-text filter across customer / PO / subject / file
let MAILT = null;     // search debounce timer (same shape as SHIPT / CODET)
let MAILPAGE = 0;     // 0-based page of the Inbox table
const PER_PAGE = 12;  // rows per page - one screenful without scrolling

// ── One pipeline, three tabs ─────────────────────────────────────────────
// Inbox → Read → Output, and nothing else (2026-10-28). There used to be a
// four-step bar on top of these same three tabs, so the pipeline was drawn
// twice - once as tabs, once as steps - and the two could disagree. The tabs
// ARE the pipeline now:
//
//   Extract on an Inbox row → the READ tab opens with that PO being read, and
//                             the output format is chosen on the page after it
//   Generate                → the OUTPUT tab opens with the file(s) on top
//
// READING is the in-flight state (the radar panel); PREVIEW is the answer from
// /api/order_preview. Both are drawn by readPanel(), so a reading can never be
// somewhere other than the tab that owns it.
let READING = null;    // {id, index} while the reading request is in flight
let LASTFILES = null;  // {files:[{fmt, name, url}]} - what the last write made

// What the Read tab shows instead of the register, or '' when nothing is open.
function readFlowPage(){
  if (PREVIEW) return previewPanel();
  if (READING) return readingPanel();
  return '';
}

// Leave the open reading/preview and go back to the register. Bumping the
// sequence counter too: a slow /api/order_preview that lands afterwards must be
// dropped, not push the user into a preview they walked away from.
function cancelReading(){
  PREVIEW_SEQ++;
  PREVIEW = null;
  READING = null;
  render();
}

async function syncDate(){
  const r = await runWithProgress(
    () => api('/api/sync_date', {date: SELDATE}),
    'Syncing ' + SELDATE, 'Reading that day from Outlook…');
  if (!r) return;
  if (r.error){ alert(r.error); return; }
  alert(r.message);
  await load();
}

// ── The customer filter: a tick list, not a drop-down ──────────────────────
// A native `<select multiple>` needs ctrl-click and paints selections as a
// highlighted range, which nobody reads as "filtered by these three". A panel
// of checkboxes is the multi-select a mouse can actually drive.
function custPickHTML(names){
  const n = CUSTPICK.length;
  const label = !n ? 'All customers'
    : (n === 1 ? CUSTPICK[0] : n + ' customers');
  let h = '<span class="mpick">'+
    '<button type="button" class="mpbtn'+(n ? ' on' : '')+'" '+
      'onclick="toggleCustPick()" '+
      'title="Filter this list by customer — tick as many as you need">'+
      esc(label)+' <span class="car">&#9662;</span></button>'+
    '<div class="mpmenu"'+(CUSTOPEN ? '' : ' hidden')+'>'+
      '<div class="mphead"><span class="muted">'+
        (names.length ? names.length+' customer(s) on this day'
                      : 'no customer on this day')+'</span>'+
        (n ? '<button type="button" class="linkbtn" '+
             'onclick="clearCustPick()">Clear</button>' : '')+
      '</div>';
  for (const c of names){
    h += '<label><input type="checkbox"'+
      (CUSTPICK.indexOf(c) >= 0 ? ' checked' : '')+
      ' value="'+esc(c)+'" onchange="pickCust(this.value, this.checked)">'+
      '<span class="ell">'+esc(c)+'</span></label>';
  }
  return h + '</div></span>';
}

function toggleCustPick(){
  CUSTOPEN = !CUSTOPEN;
  const m = document.querySelector('.mpmenu');
  if (m) m.hidden = !CUSTOPEN;
}

function pickCust(name, on){
  const i = CUSTPICK.indexOf(name);
  if (on && i < 0) CUSTPICK.push(name);
  if (!on && i >= 0) CUSTPICK.splice(i, 1);
  MAILPAGE = 0;
  render();          // the panel stays open - CUSTOPEN is what draws it
}

function clearCustPick(){
  if (!CUSTPICK.length) return;
  CUSTPICK = [];
  MAILPAGE = 0;
  render();
}

// A click anywhere else closes the panel. Clicks INSIDE it are ignored here -
// the tick handlers re-render the bar, and a tick that closed the panel would
// make picking three customers three separate trips.
document.addEventListener('click', function(ev){
  if (!CUSTOPEN) return;
  if (ev.target && ev.target.closest && ev.target.closest('.mpick')) return;
  CUSTOPEN = false;
  const m = document.querySelector('.mpmenu');
  if (m) m.hidden = true;
});

function toggleSort(){ SORTASC = !SORTASC; render(); }

// ── The Inbox's three lists ────────────────────────────────────────────────
// One screen, three questions in the order the work happens:
//   1 Inbox  - what arrived and is not done yet (the mail list, unchanged)
//   2 Read   - what has been READ and still needs an output file
//   3 Output - what was written, with the Excel and the original attachment
// Splitting them by TAB would have buried the middle one: "I read it this
// morning, where did it go?" had no answer on either of the two screens.
let ITAB = 1;
let READROWS = null;    // the register from /api/read_list, or null if not loaded
let READLOAD = false;   // a request is in flight
let READERR = '';       // why the register could not be fetched, if it could not
let READQ = '';         // free-text filter on the read list
let READOPEN = {};      // which rows are expanded
let READDETAIL = {};    // id/index -> the reading, once fetched
let READT = null;

function dayOrders(){
  return expandOrders((DATA.history || []).filter(
    m => (m.received_at||'').slice(0,10) === SELDATE));
}

function inboxTabs(){
  const day = dayOrders();
  const n1 = day.filter(m => m.status !== 'Done').length;
  const n3 = day.filter(m => m.status === 'Done').length;
  const n2 = READROWS ? READROWS.filter(r => !r.done).length : null;
  const items = [[1, 'Inbox', n1], [2, 'Read', n2], [3, 'Output', n3]];
  return '<div class="tabs" id="itabs" style="--i:'+(ITAB-1)+'">'+
    '<span class="tsink"></span>'+
    items.map(function(it){
      const i = it[0], label = it[1], n = it[2];
      return '<button class="ts'+(i === ITAB ? ' on' : '')+'" '+
        'onclick="setInboxTab('+i+')">'+
        '<span class="tlb">'+label+
        (n === null || n === undefined ? '' :
          ' <i class="tnum">'+n+'</i>')+
        '</span></button>';
    }).join('') + '</div>';
}

// Clicking a tab re-renders the page, so the new bar is a NEW element and its
// line would simply appear under the new label. To make it SLIDE, the line is
// first put where it used to be (no transition), the layout is forced, and only
// then released back to its CSS position - the browser then interpolates the
// one number it can see changing.
function setInboxTab(n){
  if (n === ITAB) return;
  const prev = ITAB;
  ITAB = n;
  MAILPAGE = 0;
  render();
  const bar = document.getElementById('itabs');
  if (bar){
    const sink = bar.querySelector('.tsink');
    const btns = bar.querySelectorAll('.ts');
    const pb = btns[prev - 1];
    if (sink && pb){
      sink.style.transition = 'none';
      sink.style.left = (pb.offsetLeft + (pb.offsetWidth - 26) / 2) + 'px';
      void sink.offsetWidth;          // force the pre-slide position to be used
      sink.style.transition = '';
      sink.style.left = '';
    }
  }
  if (n === 2) loadReads();
}

function pickDate(v){
  SELDATE = v || localToday();
  TAB = 'today';
  render();
}

// The date the Inbox answers for. It used to live in the sidebar, which is now
// a 62px rail - a date field cannot be shown in 62px, and hiding the only
// control that changes the screen behind a hover was worse than moving it.
function datePick(){
  return '<span class="muted">Date</span>'+
    '<input type="date" id="datepick" class="dpick" value="'+esc(SELDATE)+'" '+
    'title="Show POs received on a specific date" '+
    'onchange="pickDate(this.value)">';
}

function renderToday(){
  // Three tabs, one pipeline. The Read tab may be showing a reading or a
  // preview instead of the register - that choice lives in readPanel(), so the
  // tab bar on top always describes what is under it.
  if (ITAB === 2) return inboxTabs() + readPanel();
  if (ITAB === 3)
    return inboxTabs() + (LASTFILES ? outBanner() : '') +
      inboxDateBar() + renderCompleted();
  return inboxList();
}

function inboxDateBar(){
  return '<div class="filterbar"><div class="fleft">'+datePick()+
    '</div><div class="fleft"><span class="muted">'+
    fmtDate(SELDATE)+'</span></div></div>';
}

function inboxList(){
  // Split into individual order rows when there are multiple attachments (each Confirmed/extracted separately)
  const dayAll = expandOrders(DATA.history.filter(
    m => (m.received_at||'').slice(0,10) === SELDATE));
  // Unprocessed only: Done moves to Completed / Not yet, Pending, Rejected are kept
  let mails = dayAll.filter(m => m.status !== 'Done');

  const names = [...new Set(dayAll.map(dispName))].sort();
  if (CUSTPICK.length)
    mails = mails.filter(m => CUSTPICK.indexOf(dispName(m)) >= 0);
  // Free-text search. Deliberately matches the fields a person actually has in
  // front of them when hunting for an order: who sent it, the PO number, the
  // subject line, and the attachment file name. The query is trimmed HERE and
  // not in setMailQ: trimming on every keystroke ate the space while typing
  // "PO 123", and the box showed "PO123".
  const mailq = (MAILQ || '').trim().toLowerCase();
  if (mailq){
    mails = mails.filter(m => [
      dispName(m), m.po_number, m.sender, m.subject, m.customer,
      (m.att_docs || []).map(d => d.name || '').join(' ')
    ].join(' ').toLowerCase().indexOf(mailq) >= 0);
  }
  mails = mails.slice().sort((a,b) => {
    const c = (a.received_at||'').localeCompare(b.received_at||'');
    if (c !== 0) return SORTASC ? c : -c;
    if (a.id !== b.id) return a.id - b.id;
    // Orders split from the same mail are always in 1/N → N/N order
    return (a.att_seq || 0) - (b.att_seq || 0);
  });

  // ── Summary for the day (aggregated on the same date so totals add up) ──
  const onDay = a => expandOrders((a||[]).filter(
    m => (m.received_at||'').slice(0,10) === SELDATE)).length;
  const nProc = dayAll.filter(m => m.status !== 'Done').length;
  const nDone = dayAll.filter(m => m.status === 'Done').length;
  const nNot  = onDay(DATA.excluded);
  // Cancellation-flagged mail is no longer parked on a screen of its own, so
  // it is counted where it now lives: in the day's orders.
  const total = dayAll.length + nNot;
  // Also show the mail count (unique ids) to make "1 mail = N orders" clear
  const nMail = new Set([].concat(
    DATA.history, DATA.excluded||[])
    .filter(m => (m.received_at||'').slice(0,10) === SELDATE)
    .map(m => m.id)).size;

  const strip = '<div class="daystat">'+
    '<div class="ds total"><div class="dsv">'+total+'</div>'+
      '<div class="dsl">PO orders'+(nMail && nMail !== total ?
        ' &middot; from '+nMail+' emails' : '')+'</div></div>'+
    '<div class="dseq">=</div>'+
    '<div class="ds go" onclick="TAB=\\'today\\';render()">'+
      '<div class="dsv accent">'+nProc+'</div>'+
      '<div class="dsl">PO to process</div></div>'+
    '<div class="dsplus">+</div>'+
    '<div class="ds go" onclick="TAB=\\'notmypo\\';render()">'+
      '<div class="dsv">'+nNot+'</div><div class="dsl">Discarded</div></div>'+
    '<div class="dsplus">+</div>'+
    '<div class="ds go" onclick="TAB=\\'completed\\';render()">'+
      '<div class="dsv green">'+nDone+'</div>'+
      '<div class="dsl">Completed</div></div>'+
    '</div>';

  // Ticked customers, in the same bar as the search: both answer "which mail
  // is it?" and people reach for either one.
  const sel = custPickHTML(names);

  // ── The list ────────────────────────────────────────────────────────────
  // The flow pages are handled by renderToday(), not here: this function is
  // only ever the list, which is what lets the bar above it be the tab bar
  // rather than a step bar that swaps its meaning under the user.
  const isOl = (DATA.settings||{}).source === 'outlook';
  const o = (DATA.settings||{}).outlook || {};
  const bar = inboxTabs() + strip +
    // Step 1 is "choose the email" - so this row is the step. Search sits
    // beside the customer filter because they answer the same question
    // ("which mail is it?") and people reach for either one.
    '<div class="filterbar">'+
    '<div class="fleft">'+datePick()+
    // The mailbox is here as well as on Settings because it is the thing a
    // person changes when the list looks empty: "is this the right mailbox?"
    // should not need a trip to another screen. Changing it collects from the
    // new one straight away - a dropdown that only stored the name would leave
    // the table looking exactly as before.
    (isOl ? '<span class="muted">Mailbox</span> '+
      '<select id="inbox-mb" onchange="inboxMailbox(this.value)" '+
        'title="Which mailbox to read. Changing it collects from the new one.">'+
        mailboxOptions(o.mailbox_name || '')+'</select>' : '')+
    '<span class="muted">Customer</span> '+sel+
    '<span class="searchbox">'+
      '<input type="search" id="mailq" value="'+esc(MAILQ)+'" '+
        'placeholder="Search subject, PO #, sender…" '+
        'title="Filters this list: customer, PO number, sender, subject and '+
        'attachment name" '+
        'oninput="setMailQ(this.value)">'+
      (MAILQ ? '<button class="clr" onclick="setMailQ(\\'\\')" '+
        'title="Clear">&times;</button>' : '')+
    '</span>'+
    '<button class="btn" onclick="toggleSort()">'+
    (SORTASC?'Oldest first &#8595;':'Newest first &#8593;')+'</button>'+
    (isOl ? '<button class="btn" onclick="syncDate()" '+
      'title="Fetch this date from Outlook again">'+
      '&#8635; Sync this date</button>' : '')+'</div>'+
    // The Output switch left this bar on 2026-10-23: the file is chosen on step
    // 3 of the flow, next to the columns it will contain, which is the moment
    // the choice is actually being made.
    '<div class="fleft"><span class="muted">'+mails.length+
    (CUSTPICK.length || MAILQ ? ' of '+nProc : '')+'</span></div></div>';

  // Mail collected before 2026-10-26 carries no mailbox, so selecting one
  // hides it. Saying so - with the one click that files it - is the difference
  // between "the filter works" and "the filter ate my inbox".
  const mbnote = (isOl && o.mailbox_name && DATA.unclaimed)
    ? '<div class="cardnote" style="background:#fffbeb; border:1px solid '+
      'var(--border); border-radius:var(--radius); margin-bottom:16px">'+
      '<b>'+DATA.unclaimed+'</b> email(s) were collected before OrderFlow '+
      'recorded which mailbox they came from, so they are hidden while '+
      '<b>'+esc(o.mailbox_name)+'</b> is selected. '+
      '<button class="linkbtn" onclick="claimMailbox()">File them to this '+
      'mailbox</button></div>' : '';

  if (!mails.length){
    // If there is no data at all for that day, offer to fetch just that date from Outlook
    const canSync = isOl;
    if (CUSTPICK.length || MAILQ)
      return bar + mbnote + '<div class="empty">Nothing on '+fmtDate(SELDATE)+
        ' matches '+(MAILQ ? '"'+esc(MAILQ)+'"' : 'this filter')+
        (CUSTPICK.length ? ' for '+esc(CUSTPICK.join(', ')) : '')+'.'+
        '<div style="margin-top:14px"><button class="btn" '+
        'onclick="clearMailFilters()">Clear the filters</button></div></div>';
    return bar + mbnote + '<div class="empty">'+
      (dayAll.length ? 'All caught up — nothing left to process on '+
        fmtDate(SELDATE)+'.' :
       'No PO emails for '+fmtDate(SELDATE)+' yet.')+
      (canSync ? '<div style="margin-top:14px">'+
        '<button class="btn primary" onclick="syncDate()">'+
        'Sync '+esc(fmtDate(SELDATE))+' from Outlook</button></div>' : '')+
      '</div>';
  }

  // ── Pagination ─────────────────────────────────────────────────────────
  // Paged on the ATTACHMENT row, not on the mail: one email with four order
  // documents is four rows here and four separate Confirm actions, so a page
  // of 12 mails could otherwise be 40 rows of table.
  const pages = Math.max(1, Math.ceil(mails.length / PER_PAGE));
  if (MAILPAGE > pages - 1) MAILPAGE = pages - 1;
  if (MAILPAGE < 0) MAILPAGE = 0;
  const from = MAILPAGE * PER_PAGE;
  const pageRows = mails.slice(from, from + PER_PAGE);

  // What the Confirm button is about to produce used to be a paragraph here.
  // It is on the page head's marker now (see screenFaq): the switch above is
  // easy to miss, but a permanent three-line note is a heavy way to say it.
  // Sold-To / Ship-To come from the ERP account table, which is fetched per
  // customer on demand - fill the pickers in as it arrives.
  needParty(pageRows).then(() => {});
  return bar + mbnote +
    '<div class="card"><div class="cardbody">'+
    poTable(pageRows, {showCustomer:true})+'</div>'+
    pagerHTML(mails.length, pages, from, pageRows.length)+'</div>';
}

// ── Tab 2: what has already been READ ──────────────────────────────────────
// The register comes from the extraction CACHE (/api/read_list), never from the
// API: opening this tab must not buy a reading. So a row is here because a
// document was read - which is exactly what the tab claims - and "read this
// morning, where did it go?" finally has an answer.
//
// Everything is keyed by "mailId:attachmentIndex", the same pair the server's
// /api/read_detail takes. It is carried in `data-key` on the row, so no handler
// has to interpolate a string into an attribute (which is how a quote in a file
// name becomes a syntax error inside PAGE, a Python string with its own idea of
// escaping).
function loadReads(){
  if (READLOAD) return;
  READLOAD = true;
  api('/api/read_list').then(function(r){
    READLOAD = false;
    READERR = (r && r.error) || '';
    READROWS = (r && r.rows) || [];
    if (TAB === 'today' && ITAB === 2) render();
  }).catch(function(){
    READLOAD = false;
    READERR = 'The server did not answer. Nothing has been lost - reload the '+
      'page to try again.';
    if (READROWS === null) READROWS = [];
    if (TAB === 'today' && ITAB === 2) render();
  });
}

function readCountText(){
  const rows = (READROWS || []).filter(r => !r.done);
  const q = (READQ || '').trim();
  return q ? rows.filter(readMatch).length + ' of ' + rows.length
           : rows.length + ' read';
}

function readMatch(r){
  const q = (READQ || '').trim().toLowerCase();
  if (!q) return true;
  return [r.name, r.customer, r.po_number, r.sold_to, r.sold_to_name,
          r.ext].join(' ').toLowerCase().indexOf(q) >= 0;
}

function readRowsHTML(){
  const rows = (READROWS || []).filter(r => !r.done).filter(readMatch);
  if (!rows.length){
    if ((READROWS || []).length)
      return '<div class="cardnote">No read document matches that search.</div>';
    return '<div class="empty" style="margin:16px 18px">Nothing has been '+
      'read yet. Press <b>Extract</b> on an Inbox row - the reading is kept on '+
      'disk, and its file format is chosen here.</div>';
  }
  return rows.map(readRowHTML).join('');
}

function readRowHTML(r){
  const k = r.id + ':' + r.index;
  const open = !!READOPEN[k];
  const ext = String(r.ext || 'pdf').toLowerCase();
  const cls = ext === 'pdf' ? 'pdf'
            : (ext === 'xlsx' || ext === 'xls' ? 'xls' : '');
  const who = r.sold_to_name || r.sold_to || '';
  return '<div class="rlrow'+(open ? ' open' : '')+'" data-key="'+k+'">'+
    '<div class="rlmain" onclick="toggleRead(this)">'+
      '<span class="rlcar">&#9654;</span>'+
      '<div style="min-width:0">'+
        '<div class="rlfname" title="'+esc(r.name)+'">'+esc(r.name)+'</div>'+
        '<div class="rlmeta">'+esc(r.customer || '(unknown customer)')+
          (r.po_count > 1
            ? ' &middot; <b>'+r.po_count+' POs</b>'
            : (r.po_number ? ' &middot; PO '+esc(r.po_number) : ''))+
          (r.lines ? ' &middot; '+r.lines+' line'+(r.lines === 1?'':'s') : '')+
          (r.review ? ' &middot; <span class="rlwarn">'+r.review+
            ' to review</span>' : '')+
        '</div>'+
      '</div>'+
      '<div class="rlcell"><span class="ftype '+cls+'">'+
        esc(ext.toUpperCase())+'</span></div>'+
      '<div class="rlcell" title="'+esc(who)+'">'+(who ? esc(who) : '—')+
        '</div>'+
      '<div class="rlcell">'+fmtDT(r.read_at)+'</div>'+
      '<div class="rlacts">'+fmtSeg('fmt-'+k)+
      '<button class="btn sm primary genbtn" '+
        'title="Write the Order Upload in the version(s) chosen beside it: '+
        'one file per ticked version" '+
        'onclick="event.stopPropagation();readOutput(this)">Generate'+
      '</button></div>'+
    '</div>'+
    (open ? '<div class="rldetail" data-detail="'+k+'">'+
      readDetailBody(k)+'</div>' : '')+
  '</div>';
}

// Expanded row: the fields the reading actually took off the document - the
// delivery address, the two dates and the postal code - plus the lines it found.
// Served lazily because the list can hold hundreds of rows and a register is
// meant to be one cheap request.
// One row per ORDER. Used by the step-3 preview and by the Read tab: when a
// document holds four POs, the PO date and the R.D.D are four values, and a
// single cell showing one of them is how three orders got the first one's dates.
function orderTable(ords){
  let h = '<table class="ordtab"><tr><th>P/O No.</th><th>PO date</th>'+
    '<th>R.D.D</th><th class="num">Lines</th><th class="num">Printed total</th>'+
    '<th>Ship to</th></tr>';
  for (const o of ords){
    const addr = [o.address, o.city, o.zip].filter(Boolean).join(', ');
    h += '<tr><td><b>'+esc(o.po || '—')+'</b></td>'+
      '<td>'+esc(o.po_date || '—')+'</td>'+
      '<td>'+esc(o.rdd || '—')+
        (o.rdd_defaulted ? ' <span class="muted">(default)</span>' : '')+'</td>'+
      '<td class="num">'+esc(String(o.lines || 0))+'</td>'+
      '<td class="num">'+esc(o.total || '—')+'</td>'+
      '<td class="ell" style="max-width:240px" title="'+esc(addr)+'">'+
        esc(addr || '—')+'</td></tr>';
  }
  return h + '</table>';
}

function readDetailBody(k){
  const d = READDETAIL[k];
  if (!d || d === 'loading')
    return '<div class="rlnote"><span class="spin" style="border-color:#cbd5e1;'+
      'border-top-color:#64748b;margin-right:6px;vertical-align:middle"></span>'+
      'Reading the saved result…</div>';
  if (d.error)
    return '<div class="rlnote" style="color:var(--danger)">'+esc(d.error)+
      '</div>';
  let h = '';
  // A reading taken before the address block was captured has no header keys at
  // all. Saying "not printed" about those would blame the PO for something the
  // old reader never looked for.
  if (d.legacy)
    h += '<div class="rlnote" style="margin:0 0 8px;color:#92400e">'+
      'This reading predates the address capture (before 2026-10-22), so it '+
      'has no delivery address, PO date or RDD. Confirm the PO again to re-read '+
      'it - the lines below are still valid.</div>';
  const ords = d.orders || [];
  if (ords.length > 1) h += orderTable(ords);
  if ((d.fields || []).length) h += '<div class="rlgrid">';
  for (const f of (d.fields || [])){
    // The timestamp is the only machine value in here; the rest are strings
    // lifted off the document and must be shown exactly as printed.
    const val = (f[0] === 'Read at' && f[1]) ? fmtDT(f[1])
              : (f[1] ? String(f[1]) : '');
    h += '<div class="rlf"><span class="k">'+esc(f[0])+'</span>'+
      '<span class="v'+(val ? '' : ' no')+'">'+
      (val ? esc(val) : 'not printed')+'</span></div>';
  }
  if ((d.fields || []).length) h += '</div>';
  if ((d.records || []).length){
    h += '<table style="margin-top:10px"><tr><th>Material</th>'+
      '<th>Description</th><th class="num">Qty</th>'+
      '<th class="num">Unit price</th><th class="num">Amount</th></tr>';
    for (const r of d.records)
      h += '<tr'+(r.review ? ' class="needrow"' : '')+'>'+
        '<td><b>'+esc(r.code || '—')+'</b></td>'+
        '<td class="ell" style="max-width:260px">'+esc(r.desc || '')+'</td>'+
        '<td class="num">'+esc(r.qty || '')+'</td>'+
        '<td class="num">'+esc(r.price || '')+'</td>'+
        '<td class="num">'+esc(r.amount || '')+'</td></tr>';
    h += '</table>';
    if (d.more)
      h += '<div class="rlnote">+'+d.more+' more line(s) - open the file to '+
        'see all of them.</div>';
  } else {
    h += '<div class="rlnote">No line items were read from this document.</div>';
  }
  return h;
}

function loadReadDetail(k){
  if (READDETAIL[k]) return;
  READDETAIL[k] = 'loading';
  const i = k.indexOf(':');
  api('/api/read_detail', {id: +k.slice(0, i), index: +k.slice(i + 1)})
    .then(function(r){
      READDETAIL[k] = (r && !r.error) ? r
        : {error: (r && r.error) || 'could not read the saved result'};
      const el = document.querySelector('[data-detail="'+k+'"]');
      if (el) el.innerHTML = readDetailBody(k);
    });
}

function toggleRead(el){
  const row = el.closest ? el.closest('.rlrow') : el;
  if (!row) return;
  const k = row.dataset.key;
  READOPEN[k] = !READOPEN[k];
  const det = row.querySelector('.rldetail');
  if (READOPEN[k]){
    if (!det){
      const box = document.createElement('div');
      box.className = 'rldetail';
      box.setAttribute('data-detail', k);
      box.innerHTML = readDetailBody(k);
      row.appendChild(box);
    }
    row.classList.add('open');
    loadReadDetail(k);
  } else {
    if (det) det.remove();
    row.classList.remove('open');
  }
}

function clearReadQ(){
  clearTimeout(READT);
  READQ = '';
  const box = document.getElementById('readq');
  if (box) box.value = '';
  const el = document.getElementById('rllist');
  if (el) el.innerHTML = readRowsHTML();
  const c = document.getElementById('rlcount');
  if (c) c.textContent = readCountText();
}

// Typing re-filters only the LIST, not the page: the search box is outside
// `#rllist`, so it is never rebuilt and the caret never moves. That is the bug
// the Material Code search had, and this is the pattern that avoids it.
function setReadQ(v){
  READQ = v || '';
  clearTimeout(READT);
  READT = setTimeout(function(){
    const el = document.getElementById('rllist');
    if (el) el.innerHTML = readRowsHTML();
    const c = document.getElementById('rlcount');
    if (c) c.textContent = readCountText();
  }, 160);
}

function readPanel(){
  // A reading in flight, or its preview, IS the Read tab for that moment: both
  // belong to the same PO and to the same question ("what did the document
  // say, and which file do I want out of it?"). Cancel brings the register
  // back - nothing is written and the row is untouched until Generate.
  const page = readFlowPage();
  if (page) return page;
  if (READROWS === null){
    if (!READLOAD) loadReads();
    return '<div class="empty">Loading the read register…</div>';
  }
  const warn = READERR
    ? '<div class="cardnote" style="background:#fffbeb;border:1px solid '+
      '#fde68a;border-radius:var(--radius);margin-bottom:14px;color:#92400e">'+
      esc(READERR)+'</div>' : '';
  return warn + '<div class="filterbar"><div class="fleft">'+
      '<span class="searchbox">'+
        '<input type="search" id="readq" value="'+esc(READQ)+'" '+
          'placeholder="Search file, customer, PO #, Sold-To…" '+
          'oninput="setReadQ(this.value)">'+
        (READQ ? '<button class="clr" onclick="clearReadQ()" '+
          'title="Clear">&times;</button>' : '')+
      '</span>'+
      '<span class="muted" id="rlcount">'+readCountText()+'</span>'+
    '</div></div>'+
    '<div class="card"><div id="rllist">'+readRowsHTML()+'</div></div>';
}

// Write one file per ticked version, straight from a reading that already
// exists. The reading is cached, so /api/action finds it and does NOT pay for
// the document twice.
async function readOutput(btn){
  const row = btn.closest('.rlrow');
  if (!row) return;
  const k = row.dataset.key;
  const i = k.indexOf(':');
  const id = +k.slice(0, i), index = +k.slice(i + 1);
  // The switch only records the configuration; this button is what writes.
  // It reads the ticks off THIS row's switch, not the global state, so two
  // rows can be set up differently before either is generated.
  const fmts = [];
  row.querySelectorAll('.segopt input:checked').forEach(x => {
    const f = x.dataset.fmt === 'simple' ? 'simple' : 'full';
    if (fmts.indexOf(f) < 0) fmts.push(f);
  });
  const want = normFmts(fmts);
  const seg = row.querySelector('.seg');
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.classList.add('working');
  btn.innerHTML = '<span class="spin"></span>Writing…';
  if (seg) seg.classList.add('busy');
  toast(want.length > 1 ? 'Writing '+want.length+' Order Upload files…'
                        : 'Writing the Order Upload file…', true);
  const snap = rowSnapshot(id, index);
  const body = {id: id, action: 'confirm', index: index, format: want,
    sold_to: snap.sold_to, ship_to: snap.ship_to, ship: snap.ship || {}};
  let r;
  try {
    r = await api('/api/action', body);
  } catch (e){
    // The button is the only sign that anything is happening: leaving it
    // spinning on a dropped connection would block the row for good.
    r = {error: 'Could not reach OrderFlow: ' +
      (e && e.message ? e.message : e)};
  } finally {
    hideToast();
    btn.disabled = false;
    btn.classList.remove('working');
    btn.innerHTML = label;
    if (seg) seg.classList.remove('busy');
  }
  if (r.error){ alert(r.error); return; }
  delete READOPEN[k];
  delete READDETAIL[k];
  const made = (r.files || []).filter(f => f && f.url);
  // Same landing as the preview's Generate: the artifact and the register of
  // artifacts are one screen, and this row has just joined that register. A
  // toast alone left the user on a list the order had already left.
  LASTFILES = made.length ? {files: made}
    : (r.url ? {files: [{fmt: want[0], name: r.name || 'Order Upload',
                         url: r.url}]} : null);
  ITAB = 3;
  MAILPAGE = 0;
  render();
  toast('Written: '+(made.length > 1
      ? made.map(f => f.name).join(' + ')
      : (r.name || 'Order Upload'))+' — in Output');
  await load();
  READROWS = null;
  loadReads();
}

// The banner at the top of Output, right after Generate: the file(s) exist and
// the row has just joined the list underneath, so this is both the download and
// the confirmation. It sits HERE rather than over the Inbox because the Output
// tab is where the row went - putting it over the Inbox meant looking for the
// file in a list that no longer contained the order (2026-10-28).
//
// Both versions ticked means two files, so every one of them gets its own
// download button - a single "Download" over a list of two would hand back
// whichever happened to be first.
function outBanner(){
  const files = (LASTFILES && LASTFILES.files) || [];
  if (!files.length) return '';
  return '<div class="card" style="border-color:#bbf7d0; background:#f0fdf4; '+
    'margin-bottom:14px">'+
    '<div class="cardbody" style="padding:14px 18px; display:flex; '+
    'align-items:center; gap:12px; flex-wrap:wrap">'+
    '<b style="color:#166534">&#10003; Order Upload generated</b>'+
    '<span class="muted" style="font-size:13px">'+
      (files.length > 1 ? files.length+' files' : esc(files[0] ? files[0].name : ''))+
    '</span>'+
    '<span class="spacer" style="flex:1"></span>'+
    files.map(f => fmtChip(f.fmt)+'<a class="btn" href="'+esc(f.url)+
      '" download title="'+esc(f.name)+'">Download '+
      esc(f.fmt === 'simple' ? 'simple' : 'full form')+'</a>').join('')+
    '<button class="linkbtn" onclick="LASTFILES=null;render()">Dismiss</button>'+
    '</div></div>';
}

function pagerHTML(total, pages, from, shown){
  if (pages <= 1)
    return '<div class="pager"><span>Showing all '+total+'</span></div>';
  // Windowed numbers: first, last, and the neighbours of the current page.
  let nums = '';
  for (let i = 0; i < pages; i++){
    const near = Math.abs(i - MAILPAGE) <= 1;
    const edge = i === 0 || i === pages - 1;
    if (!near && !edge){
      if (nums.slice(-14) !== '<span>…</span>') nums += '<span>…</span>';
      continue;
    }
    nums += '<button class="'+(i === MAILPAGE ? 'cur' : '')+'" '+
      'onclick="mailPage('+i+')">'+(i + 1)+'</button>';
  }
  return '<div class="pager">'+
    '<button onclick="mailPage('+0+')" '+
      (MAILPAGE === 0 ? 'disabled' : '')+'>&laquo;</button>'+
    '<button onclick="mailPage('+(MAILPAGE-1)+')" '+
      (MAILPAGE === 0 ? 'disabled' : '')+'>&larr; Prev</button>'+
    '<span style="margin:0 4px">'+nums+'</span>'+
    '<button onclick="mailPage('+(MAILPAGE+1)+')" '+
      (MAILPAGE >= pages-1 ? 'disabled' : '')+'>Next &rarr;</button>'+
    '<button onclick="mailPage('+(pages-1)+')" '+
      (MAILPAGE >= pages-1 ? 'disabled' : '')+'>&raquo;</button>'+
    '<span class="spacer" style="flex:1"></span>'+
    '<span>'+(from+1)+'–'+(from+shown)+' of '+total+'</span></div>';
}

function mailPage(p){
  MAILPAGE = p;
  render();
  const card = document.querySelector('.card');
  if (card) card.scrollIntoView({block:'start', behavior:'smooth'});
}

// Typing re-renders the table, so the box is rebuilt with it. Two things the
// old version got wrong and this one does not:
//   * the caret was forced to the END (`setSelectionRange(len, len)`), which
//     made it impossible to fix a typo in the middle of a search term;
//   * the value was trimmed on every keystroke, so the space in "PO 123" was
//     eaten as soon as it was typed.
// The caret is now put back where the user had it, and the debounce keeps the
// box untouched while they are still typing.
function setMailQ(v){
  const box = document.getElementById('mailq');
  const pos = (box && box.selectionStart != null)
    ? box.selectionStart : (v || '').length;
  MAILQ = (v || '');
  MAILPAGE = 0;
  clearTimeout(MAILT);
  MAILT = setTimeout(() => {
    render();
    const nb = document.getElementById('mailq');
    if (nb){
      nb.focus();
      try { nb.setSelectionRange(pos, pos); } catch (e) {}
    }
  }, 180);
}

function clearMailFilters(){
  clearTimeout(MAILT);          // drop a pending search re-render
  MAILQ = ''; CUSTPICK = []; MAILPAGE = 0;
  render();
}

// Completed — and Order Upload, which are the same list seen from two ends.
// A confirmed PO is "completed" the moment it is written, and "uploaded" once
// it has been keyed into ERP; splitting them meant two screens over one set of
// rows, each showing half the state. Here every confirmed PO of the day is
// listed once, with its Order Upload file and its ERP status in the row.
function renderCompleted(){
  const all = expandOrders(DATA.history).filter(m => m.status === 'Done');
  const mails = all.filter(
    m => (m.received_at||'').slice(0,10) === SELDATE)
    .sort((a,b) => (a.received_at||'').localeCompare(b.received_at||''));
  const others = all.length - mails.length;
  const note = others
    ? '<div class="cardnote" style="background:#fffbeb; border:1px solid '+
      'var(--border); border-radius:var(--radius); margin-bottom:16px">'+
      others+' more completed PO(s) on other dates. Change the date above '+
      'to see them.</div>' : '';
  if (!mails.length)
    return note + '<div class="empty">Nothing completed on '+
      fmtDate(SELDATE)+'.</div>';
  // The workflow note that used to sit here is the page head's marker now. The
  // "n still to upload" it carried is per row in the ERP column, so nothing is
  // lost by dropping the sentence.
  let h = note + '<div class="card"><div class="cardbody">';
  // Percentages for the same reason as the Inbox (see poTable): a <col> only
  // honours `width`, and the column left without one becomes the AUTO column
  // that takes all the surplus.
  //
  // Re-cut 2026-10-27: the old set asked for a 1320px floor inside a content
  // column that is ~930px on a 1600-wide display, so the table scrolled and the
  // ERP buttons sat against (or past) the card edge. Nine columns at 920 is
  // tight but honest: every width below was chosen against the longest value
  // that column actually holds, and Subject/Upload keep the slack because they
  // are the two a person reads.
  h += '<table class="fixed" style="min-width:920px"><colgroup>'+
    '<col style="width:6%"><col style="width:7%"><col style="width:9%">'+
    '<col style="width:9%"><col style="width:20%">'+
    '<col style="width:8%"><col style="width:7%">'+
    '<col style="width:21%"><col style="width:13%"></colgroup>'+
    '<tr><th>Status</th><th>Received</th><th>Customer</th>'+
    '<th>Sender</th><th>Subject</th><th>Attachments</th>'+
    '<th>PO #</th><th>Upload File</th><th>ERP</th></tr>';
  for (const m of mails){
    h += '<tr><td>'+statusDot(m)+'</td>'+
      '<td>'+fmtDT2(m.received_at)+'</td>'+
      '<td class="ell" title="'+esc(dispName(m))+'">'+esc(dispName(m))+'</td>'+
      '<td class="ell" title="'+esc(m.sender)+'">'+esc(m.sender)+'</td>'+
      '<td class="ell" title="'+esc(m.subject)+'">'+
        '<a href="#" class="subjlink" '+
        'onclick="openMail('+m.id+');return false">'+seqBadge(m)+
        esc(m.subject)+'</a></td>'+
      '<td>'+attCell(m)+'</td>'+
      '<td class="ell" title="'+esc(m.po_number||'')+'"><b>'+
        esc(m.po_number||'—')+'</b></td>'+
      '<td>'+erpFileCell(m)+'</td>'+
      '<td>'+erpMarkCell(m)+'</td>'+
      '</tr>';
  }
  return h + '</table></div></div>';
}

// The generated Order Upload file(s) for a row, or why there is not one. Same
// three states the old Order Upload screen drew, because a Confirmed mail
// whose extraction is still running (or failed) must not look like a success.
//
// Two files since 2026-10-27: ticking both versions writes both, and each gets
// its own link and its own chip, so "which one is this?" is answerable without
// opening the file.
function erpFileCell(m){
  const files = [m.erp_file, m.erp_file2].filter(x => !!x);
  if (files.length){
    return files.map((f, i) => {
      const base = f.split(/[\\\\/]/).pop();
      // The file name says which version it is (the simple sheet is written as
      // OrderUploadSimple_...), so the row can show it without asking.
      // `.erpf` is a flex line: the chip keeps its width, the NAME ellipsises.
      // Without it the two long names were hard-clipped by `table.fixed td
      // { overflow:hidden }`, i.e. cut mid-word with no "…" to say so.
      return '<div class="erpf">'+
        fmtChip(/^OrderUploadSimple/i.test(base) ? 'simple' : 'full')+
        '<a href="#" class="attlink" title="'+esc(f)+'" '+
        'onclick="openErp('+m.id+','+(i+1)+');return false">'+
        '&#128202; '+esc(base)+'</a></div>';
    }).join('');
  }
  if (m.note === 'Extracting…'){
    // Confirm marks status=Done before extraction runs, so a poll landing in
    // that window (another tab, or the background sync poll) must not read
    // this as a failure - it is still working.
    return '<span class="muted"><span class="spin" style="border-color:'+
      '#cbd5e1;border-top-color:#64748b;vertical-align:middle;'+
      'margin-right:5px"></span>Extracting…</span>';
  }
  const why = m.note ? esc(m.note.slice(0,140)) : 'no output file was produced';
  return '<span style="color:var(--danger)" title="'+why+
    '">&#9888; Not generated — '+why+'</span>';
}

// The ERP column: Mark uploaded, or the uploaded mark plus Undo.
//
// .erpacts lets the two wrap onto separate lines. The column is ~115px at the
// table's floor and "Mark uploaded" alone is most of it, so on one line they
// used to run off the cell - which reads as a broken table rather than as a
// narrow column (2026-10-27).
function erpMarkCell(m){
  const undo = ' <button class="btn" onclick="undoDone('+m.id+
    (m.att_index===undefined?'':','+m.att_index)+')">Undo</button>';
  if (m.erp_uploaded)
    return '<div class="erpacts"><span class="muted" title="Keyed into ERP">'+
      '&#10003; uploaded</span>'+undo+'</div>';
  return '<div class="erpacts"><button class="btn primary" '+
    'onclick="erpUpload('+m.id+
    (m.att_index===undefined?'':','+m.att_index)+')">Mark uploaded</button>'+
    undo+'</div>';
}

async function undoDone(id, index){
  const base = {id:id};
  if (index !== undefined && index !== null) base.index = index;
  const r = await api('/api/update',
    Object.assign({field:'status', value:'Not yet'}, base));
  if (r && r.error){ alert('Undo failed: '+r.error); return; }
  await api('/api/update', Object.assign({field:'confirmed_at', value:''}, base));
  await api('/api/update', Object.assign({field:'erp_file', value:''}, base));
  // Both slots: a row that was written in both versions must lose both, or the
  // stale simple sheet stays listed against a PO that is back in the Inbox.
  await api('/api/update', Object.assign({field:'erp_file2', value:''}, base));
  // Clear the uploaded mark too: reprocessing this order must put it back in
  // the Order Upload list, not leave it hidden by the previous upload.
  await api('/api/update', Object.assign({field:'erp_uploaded', value:0}, base));
  toast('Sent back to Today\\'s PO');
  await load();
}

// ── Dashboard ──────────────────────────────────────────────────────────────
// Replaces the Reports wall: five tables that all answered "what happened" and
// none that answered "how are we doing". What is left is the question a shift
// lead actually asks, in order - how many POs did we finish this week / this
// month / in the last 30 days, is that better or worse than the same stretch
// before it, what does the month look like day by day, and who did the work
// come from.
//
// One number is deliberately absent: anything derived from line VALUES. The
// database holds no prices (the reading does), so a "revenue" card would be a
// guess dressed up as a fact.
//
// A PO counts on the day it was COMPLETED, not the day the mail arrived.
// "How many did we finish" is a question about output, and a PO that arrived
// Friday night and was confirmed Monday belongs to Monday.
const DASH_DAYS = 30;

function doneDay(m){
  return String(m.confirmed_at || m.received_at || '').slice(0, 10);
}

function doneOrders(){
  return expandOrders((DATA.history || []).filter(m => m.status === 'Done'));
}

function addDays(iso, n){
  const d = new Date(+iso.slice(0,4), +iso.slice(5,7)-1, +iso.slice(8,10));
  d.setDate(d.getDate() + n);
  return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+
    String(d.getDate()).padStart(2,'0');
}

function mondayOf(iso){
  const d = new Date(+iso.slice(0,4), +iso.slice(5,7)-1, +iso.slice(8,10));
  const dow = (d.getDay() + 6) % 7;            // Mon = 0
  return addDays(iso, -dow);
}

function monthStart(iso){ return iso.slice(0,8) + '01'; }

function prevMonthStart(iso){
  let y = +iso.slice(0,4), m = +iso.slice(5,7) - 1;
  if (m === 0){ m = 12; y -= 1; }
  return y + '-' + String(m).padStart(2,'0') + '-01';
}

function monthEnd(iso){
  const y = +iso.slice(0,4), m = +iso.slice(5,7);
  const last = new Date(y, m, 0).getDate();    // day 0 of the next month
  return iso.slice(0,8) + String(last).padStart(2,'0');
}

function dayLabel(iso){
  const d = new Date(+iso.slice(0,4), +iso.slice(5,7)-1, +iso.slice(8,10));
  if (isNaN(d)) return iso;
  return d.toLocaleDateString('en-US', {month:'short', day:'numeric'});
}

function countBetween(byDay, from, to){
  let n = 0;
  for (const k in byDay) if (k >= from && k <= to) n += byDay[k];
  return n;
}

// 环比. The comparison period is named in the tooltip, not implied by the
// colour: "+12%" is meaningless until you know it is measured against last
// week's Mon-Sat and not against a full week.
function deltaHTML(cur, prev, what){
  const tip = 'vs ' + what + ': ' + prev;
  if (!prev){
    if (!cur) return '<span class="delta flat" title="' + esc(tip) +
      ' - nothing in either period">0%</span>';
    return '<span class="delta up" title="' + esc(tip) +
      ' - nothing in the period before">new</span>';
  }
  const pct = Math.round((cur - prev) / prev * 100);
  const cls = pct > 0 ? 'up' : (pct < 0 ? 'down' : 'flat');
  const ar = pct > 0 ? '&#9650;' : (pct < 0 ? '&#9660;' : '&#8212;');
  return '<span class="delta ' + cls + '" title="' + esc(tip) + '">' +
    '<span class="ar">' + ar + '</span>' + Math.abs(pct) + '%</span>';
}

function kpiCard(cls, label, value, sub, delta){
  return '<div class="kpi2 ' + cls + '">' + delta +
    '<div class="klab">' + label + '</div>' +
    '<div class="kval">' + value + '</div>' +
    '<div class="ksub">' + sub + '</div></div>';
}

// The line. Hand-drawn SVG rather than a chart library: the page ships as one
// HTML string with no build step, and a library for thirty points would weigh
// more than the whole stylesheet.
//
// The curve is a cubic with horizontal tangents at every point - `C mid,y0
// mid,y1 x1,y1`. That is smooth without overshooting, which matters because
// these are COUNTS: a spline that dips below zero between two days shows a day
// with -1 POs, and a number that cannot exist undermines the ones that do.
function trendSVG(days){
  // Drawn at a fixed aspect and scaled uniformly: the SVG fills a box whose
  // ratio it shares (see .trendwrap), so the labels keep their shape. A
  // stretched `preserveAspectRatio="none"` would make every label wide and
  // every dot an ellipse the moment the window was resized.
  const W = 1000, H = 260, L = 46, R = 18, T = 18, B = 34;
  const iw = W - L - R, ih = H - T - B;
  const max = Math.max(1, Math.max.apply(null, days.map(d => d.n)));
  const x = i => days.length < 2 ? L + iw / 2 : L + iw * i / (days.length - 1);
  const y = n => T + ih - ih * n / max;
  const f = v => v.toFixed(1);

  let line = '';
  days.forEach(function(d, i){
    if (!i){ line = 'M' + f(x(i)) + ',' + f(y(d.n)); return; }
    const px = x(i), py = y(d.n), qx = (x(i-1) + px) / 2;
    line += ' C' + f(qx) + ',' + f(y(days[i-1].n)) + ' ' +
            f(qx) + ',' + f(py) + ' ' + f(px) + ',' + f(py);
  });
  const base = T + ih;
  const area = line + ' L' + f(x(days.length-1)) + ',' + base +
    ' L' + f(x(0)) + ',' + base + ' Z';

  let g = '<defs>' +
    '<linearGradient id="tline" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="#60a5fa"/>' +
      '<stop offset="1" stop-color="#2563eb"/></linearGradient>' +
    '<linearGradient id="tfill" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="#93c5fd" stop-opacity=".30"/>' +
      '<stop offset="1" stop-color="#93c5fd" stop-opacity="0"/></linearGradient>' +
    '</defs>';

  // Three grid lines, top / middle / zero - enough to read a value off the
  // chart without turning it into graph paper.
  [0, 0.5, 1].forEach(function(k){
    const py = T + ih * k;
    g += '<line class="' + (k === 1 ? 'zl' : 'gl') + '" x1="' + L + '" y1="' +
      f(py) + '" x2="' + (W - R) + '" y2="' + f(py) + '"/>' +
      '<text class="lab" x="' + (L - 9) + '" y="' + f(py + 4) +
      '" text-anchor="end">' + Math.round(max * (1 - k)) + '</text>';
  });

  g += '<path d="' + area + '" fill="url(#tfill)"/>' +
       '<path class="ln" d="' + line + '" stroke="url(#tline)"/>';

  // A dot per day, last one filled. Each carries its own <title>, so hovering
  // it says the date and the count without a tooltip layer of our own.
  const step = Math.max(1, Math.round((days.length - 1) / 5));
  days.forEach(function(d, i){
    const last = i === days.length - 1;
    g += '<g class="pt">' +
      '<circle class="hit" cx="' + f(x(i)) + '" cy="' + f(y(d.n)) + '" r="9"/>' +
      '<circle class="dot' + (last ? ' last' : '') + '" cx="' + f(x(i)) +
        '" cy="' + f(y(d.n)) + '" r="' + (last ? 3.4 : 2.4) + '"/>' +
      '<title>' + esc(dayLabel(d.d)) + ' \u00b7 ' + d.n + ' completed</title>' +
      '</g>';
    if (i % step === 0 || last)
      g += '<text class="lab" x="' + f(x(i)) + '" y="' + (H - 6) +
        '" text-anchor="' + (last ? 'end' : (i === 0 ? 'start' : 'middle')) +
        '">' + esc(dayLabel(d.d)) + '</text>';
  });

  return '<div class="trendwrap"><svg class="trend" viewBox="0 0 ' + W + ' ' +
    H + '" role="img" aria-label="Completed POs per day, last ' +
    days.length + ' days">' + g + '</svg></div>';
}

// "Which customers is the work coming from" - lengths, not angles. A pie would
// need a legend to be readable at all, and these are the same numbers in a form
// you can compare down the column.
function shareCard(done, from, to){
  const per = {};
  for (const m of done){
    const d = doneDay(m);
    if (d < from || d > to) continue;
    const who = dispName(m);
    per[who] = (per[who] || 0) + 1;
  }
  const rows = Object.keys(per).map(k => ({name: k, n: per[k]}))
    .sort((a, b) => b.n - a.n || a.name.localeCompare(b.name));
  const total = rows.reduce((s, r) => s + r.n, 0);
  if (!total)
    return '<div class="card"><div class="cardhead"><h3>Customer share</h3>' +
      '</div><div class="cardnote">Nothing completed in this window.</div></div>';
  let h = '<div class="card"><div class="cardhead"><h3>Customer share</h3>' +
    '<span class="count">' + total + ' completed &middot; ' + rows.length +
    ' customer' + (rows.length === 1 ? '' : 's') + '</span></div>';
  // The bar length IS the percentage printed at the end of the row. Scaling it
  // to the leader instead (what this did first) made three customers on 2 POs
  // each draw three full-width bars next to the label "33%", which reads as a
  // bug even though nothing was wrong with the numbers.
  for (const r of rows)
    h += '<div class="share">' +
      '<span class="nm" title="' + esc(r.name) + '">' + esc(r.name) + '</span>' +
      '<span class="bar"><i style="width:' +
        Math.max(2, Math.round(r.n / total * 100)) + '%"></i></span>' +
      '<span class="n">' + r.n + '</span>' +
      '<span class="pc">' + Math.round(r.n / total * 100) + '%</span></div>';
  return h + '</div>';
}

function renderDashboard(){
  const today = localToday();
  const done = doneOrders();
  const byDay = {};
  for (const m of done){
    const d = doneDay(m);
    if (d) byDay[d] = (byDay[d] || 0) + 1;
  }

  // ── The three cards ─────────────────────────────────────────────────────
  // This week: Monday to today, against the SAME number of days last week -
  // comparing a half-finished Monday-to-Wednesday with a full Mon-Sun is how a
  // dashboard reports a collapse every Wednesday.
  const mon = mondayOf(today);
  const wkDays = Math.round(
    (new Date(+today.slice(0,4), +today.slice(5,7)-1, +today.slice(8,10)) -
     new Date(+mon.slice(0,4), +mon.slice(5,7)-1, +mon.slice(8,10))) / 86400000) + 1;
  const prevMon = addDays(mon, -7);
  const prevWkTo = addDays(prevMon, wkDays - 1);
  const thisWeek = countBetween(byDay, mon, today);
  const lastWeek = countBetween(byDay, prevMon, prevWkTo);

  // Month to date, against the same day-of-month in the previous month.
  const ms = monthStart(today);
  const dom = +today.slice(8, 10);
  const pms = prevMonthStart(today);
  const pmToRaw = addDays(pms, dom - 1);
  const pmTo = pmToRaw > monthEnd(pms) ? monthEnd(pms) : pmToRaw;
  const thisMonth = countBetween(byDay, ms, today);
  const lastMonth = countBetween(byDay, pms, pmTo);

  // The rolling window the chart below covers, and its own 环比.
  const from30 = addDays(today, -(DASH_DAYS - 1));
  const prevFrom = addDays(today, -(DASH_DAYS * 2 - 1));
  const prevTo = addDays(today, -DASH_DAYS);
  const last30 = countBetween(byDay, from30, today);
  const prev30 = countBetween(byDay, prevFrom, prevTo);

  let h = '<div class="kpirow dash">' +
    kpiCard('', 'Completed &middot; this week', thisWeek,
      dayLabel(mon) + ' – ' + dayLabel(today) +
      ' &middot; ' + lastWeek + ' over the same ' + wkDays + ' day' +
      (wkDays === 1 ? '' : 's') + ' last week',
      deltaHTML(thisWeek, lastWeek,
        'the same ' + wkDays + ' days last week (' +
        dayLabel(prevMon) + ' – ' + dayLabel(prevWkTo) + ')')) +
    kpiCard('g', 'Completed &middot; this month', thisMonth,
      dayLabel(ms) + ' – ' + dayLabel(today) +
      ' &middot; ' + lastMonth + ' to the same day last month',
      deltaHTML(thisMonth, lastMonth,
        'the same ' + dom + ' days last month')) +
    kpiCard('a', 'Completed &middot; last ' + DASH_DAYS + ' days', last30,
      'about ' + (last30 / DASH_DAYS).toFixed(1) + ' per day &middot; ' +
      prev30 + ' in the ' + DASH_DAYS + ' days before',
      deltaHTML(last30, prev30, 'the previous ' + DASH_DAYS + ' days')) +
    '</div>';

  if (!done.length){
    h += '<div class="empty">No PO has been completed yet. Confirm one from ' +
      'the Inbox and this page starts keeping score.</div>';
    return h;
  }

  // ── The trend ───────────────────────────────────────────────────────────
  const days = [];
  for (let i = DASH_DAYS - 1; i >= 0; i--){
    const d = addDays(today, -i);
    days.push({d: d, n: byDay[d] || 0});
  }
  // The stat line that used to run under this title was a whole row of prose
  // for two numbers. The numbers are in the legend slot now, which was showing
  // a dot and the words "completed per day" - a single-series chart does not
  // need a legend to say what its only series is.
  h += '<div class="card chartcard">' +
    '<div class="charthead"><h3>Completed POs &mdash; last ' + DASH_DAYS +
      ' days' + faq('trend') + '</h3>' +
      '<span class="legend"><i></i>' + last30 + ' total &middot; peak ' +
      Math.max.apply(null, days.map(d => d.n)) + ' a day</span></div>' +
    '<div class="chartwrap">' + trendSVG(days) + '</div></div>';

  // ── Who the work comes from ─────────────────────────────────────────────
  h += shareCard(done, from30, today);
  return h;
}

async function erpUpload(id, index){
  // "Uploaded to ERP" - the only thing that sets erp_uploaded, and therefore
  // the only way a row leaves the Order Upload list. ERP upload itself is
  // still manual (open the file, upload it), so this records that it happened
  // rather than performing it.
  const base = {id:id, field:'erp_uploaded', value:1};
  if (index !== undefined && index !== null) base.index = index;
  const r = await api('/api/update', base);
  if (r && r.error){ alert('Could not mark it uploaded: '+r.error); return; }
  toast('Marked as uploaded to ERP');
  await load();
}

async function openErp(id, which){
  toast('Opening ERP Excel…');
  const r = await api('/api/openerp', {id:id, which: which || 1});
  if (r.error) alert(r.error);
}

async function applyMaster(){
  const r = await api('/api/master_apply', {});
  alert(r.message || r.error);
  await load();
}

// Unmatched mail is grouped by DOMAIN: matching looks at the domain alone, and
// the domain IS the identity now. A domain no row of the Ship-To master
// carries cannot be matched, so it stays here until somebody adds a row for it.
function renderUnmatchedSection(){
  const un = {};
  (DATA.unclassified||[]).forEach(m => {
    const k = senderDomain(m);
    (un[k] = un[k] || []).push(m);
  });
  const doms = Object.keys(un).sort();
  if (!doms.length) return '';
  let h = '<div class="card" style="border-color:#fcd34d">'+
    '<div class="cardhead"><h3>Unmatched Domains ('+doms.length+')</h3>'+
    '<span class="count">A mail is matched by the domain of its sender and '+
    'by nothing else. A domain the domain table does not carry cannot be '+
    'matched — add a row for it and every stored mail from it is '+
    'reclassified</span></div>'+
    '<div class="cardbody"><table>'+
    '<tr><th>Domain</th><th class="num">Emails</th><th>Example sender</th>'+
    '<th>Last Subject</th><th>Action</th></tr>';
  for (const d of doms){
    const g = un[d].slice().sort(
      (a,b) => (b.received_at||'').localeCompare(a.received_at||''));
    const has = d ? domainKnown(d) : false;
    h += '<tr class="warnrow"><td class="ell">'+
      '<b>'+esc(d ? '@'+d : '(no domain in the address)')+'</b>'+
      (has ? '<div class="dupflag">claimed by a domain row, but these mails '+
             'predate it — run Re-match below</div>' : '')+
      '</td>'+
      '<td class="num">'+g.length+'</td>'+
      '<td class="ell" title="'+esc(g[0].sender)+'">'+esc(g[0].sender)+'</td>'+
      '<td class="ell" title="'+esc(g[0].subject)+'">'+esc(g[0].subject)+'</td>'+
      '<td>'+(d
        ? '<button class="linkbtn" onclick="addDomainRow('+
          JSON.stringify(d).replace(/"/g,'&quot;')+')">+ Add a domain row</button>'
        : '<span class="muted">no domain in the address</span>')+
      '</td></tr>';
  }
  return h + '</table></div></div>';
}

// Claim a domain: the identity lives in the DOMAIN table, so claiming means
// adding a row there. Only the domain is filled in - the customer name is
// typed next to it, and until it matches a Ship-To name no pair is owned.
// (This used to add a Ship-To row carrying just the domain; the domain is no
// longer a column of that table, so it would have been dropped on arrival.)
async function addDomainRow(domain){
  if (!confirm('Add a domain row for @'+domain+'?\\n\\n'+
      'Fill in the customer name on the Customer Master screen - the name is '+
      'what joins it to the Ship-To table, so mail from this domain is matched '+
      'as soon as the two agree.')) return;
  const r = await api('/api/domain_row_add', {row: {domain: domain}});
  if (r.error){ alert(r.error); return; }
  await forgetParty();
  DOM.q = domain;
  DOM.offset = 0;
  TAB = 'master';
  toast('Domain row added for @'+domain+' — set its customer name');
  await load();
}

// ── Quick Convert: pick PO files from a folder, or drop them ──
// The folder route is the primary one: OrderFlow opens the file itself, which
// is the only way a DRM-protected PO can be read. A browser upload always
// arrives encrypted because the browser is not an authorised process.
let QFILES = [];      // dropped files [{name, size, data(base64)}]
let QRESULT = null;
let QDONE = [];       // files converted in this session (newest first)
let QFOLDER = null;   // {folder, files:[{name,path,size,kind}]}
let QSEL = [];        // selected paths from the folder listing

function renderQuick(){
  const folder = (QFOLDER && QFOLDER.folder) || (DATA && DATA.quick_folder) || '';
  let h = '<div class="card setcard"><div class="cardhead">'+
    '<h3>PO folder' + faq('quickfolder') + '</h3></div><div class="setbody">'+
    '<div class="inline">'+
    '<input type="text" id="q-folder" placeholder="D:\\\\POs" value="'+
      esc(folder)+'" style="flex:1" '+
      'onkeydown="if(event.key===\\'Enter\\')qScan()">'+
    '<button class="btn primary" onclick="qBrowse()">Browse…</button>'+
    '</div>';

  if (QFOLDER){
    const files = QFOLDER.files || [];
    if (!files.length){
      h += '<div class="cardnote" style="margin-top:14px">No PDF or Excel '+
        'file in this folder.</div>';
    } else {
      h += '<div class="inline" style="margin:14px 0 8px">'+
        '<span class="muted">'+files.length+' file(s)</span>'+
        '<span class="spacer" style="flex:1"></span>'+
        '<button class="linkbtn" onclick="qSelAll(true)">Select all</button>'+
        '<button class="linkbtn" onclick="qSelAll(false)">Clear</button>'+
        '</div><div class="accres">';
      files.forEach(f => {
        const on = QSEL.indexOf(f.path) >= 0;
        h += '<label class="accpick'+(on?' on':'')+'">'+
          '<input type="checkbox" '+(on?'checked ':'')+'value="'+
          esc(f.path)+'" onchange="qSelToggle(this)">'+
          '<span class="accname">'+esc(f.name)+'</span>'+
          '<span class="spacer" style="flex:1"></span>'+
          '<span class="muted">'+esc(f.kind)+'</span>'+
          '<span class="muted">'+fmtKB(f.size)+'</span></label>';
      });
      h += '</div>';
    }
  }
  h += '</div></div>';

  // Secondary: drag and drop, for files that are not DRM protected
  h += '<div class="card"><div class="cardbody">'+
    '<div id="dropzone" class="dropzone">'+
    '<div class="dzfold" id="dzfold" role="button" tabindex="0" '+
      'aria-label="Choose files to read">'+
      '<div class="dzback"></div>'+
      '<div class="dzleaf dzl4"></div>'+
      '<div class="dzleaf dzl3"></div>'+
      '<div class="dzleaf dzl2"></div>'+
      '<div class="dzfront"></div>'+
    '</div>'+
    '<div class="dztitle"><span class="t1">…or drop files here</span>'+
      '<span class="t2">Let go to read</span></div>'+
    '<div class="dzsub">Works for files without DRM protection '+
    '&nbsp;·&nbsp; or <a href="#" onclick="document.getElementById('+
    '\\'qfile\\').click();return false">browse</a>'+faq('quickdrop')+'</div>'+
    '<input type="file" id="qfile" multiple accept=".pdf,.xlsx,.xlsm,.xls,'+
    '.csv" style="display:none" onchange="qPick(this.files)">'+
    '</div>';

  if (QFILES.length){
    h += '<div class="qfiles">';
    QFILES.forEach((f, i) => {
      h += '<div class="qfile"><span>&#128196; '+esc(f.name)+'</span>'+
        '<span class="muted">'+fmtKB(f.size)+'</span>'+
        '<button class="linkbtn" onclick="qRemove('+i+')">Remove</button>'+
        '</div>';
    });
    h += '</div>';
  }

  const n = QSEL.length + QFILES.length;
  h += '<div class="setactions">'+
    (n ? '<button class="btn" onclick="qClear()">Clear</button>' : '')+
    '<div class="spacer" style="flex:1"></div>'+
    '<button class="btn primary"'+(n?'':' disabled')+
    ' onclick="qConvert()">Extract'+(n?' ('+n+')':'')+'</button>'+
    '</div></div></div>';

  if (QRESULT) h += quickResultCard();
  if (QDONE.length) h += quickDoneCard();
  return h;
}

async function qBrowse(){
  const cur = (document.getElementById('q-folder')||{}).value || '';
  toast('Opening folder picker…');
  const r = await api('/api/pick_folder', {start: cur});
  if (r.error){ alert(r.error); return; }
  if (!r.folder) return;               // user cancelled the dialog
  document.getElementById('q-folder').value = r.folder;
  await qScan();
}

async function qScan(){
  const v = (document.getElementById('q-folder')||{}).value || '';
  if (!v.trim()){ alert('Type the folder path first.'); return; }
  toast('Reading folder…');
  const r = await api('/api/quick_scan', {folder: v});
  if (r.error){ alert(r.error); return; }
  // Drop anything previously dragged in. Extract sends the dropped files
  // AND the ticked paths together, so a file left over from an earlier drag
  // would still be uploaded - and if that one is DRM-protected the whole
  // request is refused, making the folder route look broken when it is not.
  QFOLDER = r; QSEL = []; QFILES = []; QRESULT = null;
  render();
}

function qSelToggle(el){
  const i = QSEL.indexOf(el.value);
  if (el.checked && i < 0) QSEL.push(el.value);
  if (!el.checked && i >= 0) QSEL.splice(i, 1);
  el.parentNode.classList.toggle('on', el.checked);
  QRESULT = null;
  render();
}

function qSelAll(on){
  QSEL = on ? ((QFOLDER && QFOLDER.files) || []).map(f => f.path) : [];
  QRESULT = null;
  render();
}

// Files already converted in this session - lets the user keep going and
// still get back to anything they made a minute ago.
function quickDoneCard(){
  let h = '<div class="card"><div class="cardhead">'+
    '<h3>Converted in this session</h3>'+
    '<span class="count">'+QDONE.length+'</span>'+
    '<span class="spacer" style="flex:1"></span>'+
    '<button class="linkbtn" onclick="QDONE=[];render()">Clear list</button>'+
    '</div><div class="cardbody"><table>'+
    '<tr><th>Source</th><th>PO #</th><th>Version</th><th>Lines</th>'+
    '<th>File</th><th></th></tr>';
  QDONE.forEach((d, i) => {
    // One row per CONVERSION, one link per file: with both versions ticked a
    // single cell holds two downloads, and each keeps its own chip so it is
    // clear which is which.
    const files = d.files && d.files.length ? d.files
      : [{fmt: d.fmt, name: d.name, url: d.url}];
    h += '<tr><td>'+esc(d.source)+'</td>'+
      '<td>'+(d.po ? '<b>'+esc(d.po)+'</b>' : '<span class="muted">—</span>')+
      '</td><td>'+files.map(f => fmtChip(f.fmt)).join(' ')+
      '</td><td>'+d.count+'</td>'+
      '<td class="ell" title="'+esc(files.map(f=>f.name).join('\\n'))+'">'+
      files.map(f => '<a href="'+esc(f.url)+'" download class="attlink">'+
        '&#11015; '+esc(f.name)+'</a>').join('<br>')+
      '</td>'+
      '<td><button class="linkbtn" onclick="qReopen('+i+')">Reopen</button>'+
      '</td></tr>';
  });
  return h + '</table></div></div>';
}

// Small badge saying which version a generated file is.
function fmtChip(fmt){
  const s = (fmt === 'simple');
  return '<span class="fmtchip'+(s?' simple':'')+'">'+
    (s ? 'Simple' : 'Full form')+'</span>';
}

function qReopen(i){
  const d = QDONE[i];
  if (!d) return;
  QRESULT = {lines: JSON.parse(JSON.stringify(d.lines)), po_number: d.po,
    messages: d.messages || [], downloaded: d.name};
  QFILES = [];
  // Put the account numbers back too, so Reopen + Download reproduces the
  // same file rather than one with a blank Sold-To / Ship-To.
  QPARTY = {customer: d.customer || '', sold_to: d.sold_to || '',
            ship_to: d.ship_to || ''};
  if (QPARTY.customer && !PARTY[QPARTY.customer] &&
      domainKnown(QPARTY.customer))
    api('/api/party_options', {domain: QPARTY.customer, role: ''})
      .then(r => { PARTY[QPARTY.customer] = r; render(); })
      .catch(() => {});
  // Go back to the version(s) this file was made in, so Download reproduces it
  // instead of quietly switching to whatever the switch is on now.
  if (d.fmts && d.fmts.join() !== erpFmts().join()) setErpFmts(d.fmts);
  render();
  window.scrollTo({top: 0, behavior: 'smooth'});
}

function fmtKB(n){
  if (!n && n !== 0) return '';
  return n > 1048576 ? (n/1048576).toFixed(1)+' MB'
                     : Math.max(1, Math.round(n/1024))+' KB';
}

function quickResultCard(){
  const r = QRESULT;
  if (r.error)
    return '<div class="card" style="border-color:var(--danger)">'+
      '<div class="cardhead"><h3>Could not convert</h3></div>'+
      '<div class="cardbody"><pre class="qlog">'+esc(r.error)+'</pre>'+
      '</div></div>';
  const lines = r.lines || [];
  const nUse = lines.filter(l => l.use !== false).length;
  // The same switch the Inbox uses (2026-10-27). It replaced a split button
  // whose caret chose "the other version": with both tickable there is no
  // "other" to choose, and one Download that writes everything ticked is the
  // whole interaction. `onlySimple` still matters, because the full form is
  // what carries the Sold-To / Ship-To block - with both ticked, that block is
  // needed, so the card must not hide it just because Simple is one of them.
  const fmts = erpFmts();
  const onlySimple = fmts.length === 1 && fmts[0] === 'simple';
  let h = '<div class="card"><div class="cardhead">'+
    '<h3>Review and download' + faq('quickresult') + '</h3>'+
    '<span class="count">'+nUse+(nUse === lines.length ? '' :
      ' of '+lines.length)+' line(s)</span>'+
    '<span class="spacer" style="flex:1"></span>'+
    (nUse
      ? fmtSeg('quick')+
        '<button class="btn primary" title="Write the Order Upload in the '+
          'version(s) ticked beside it: one file per ticked version" '+
          'onclick="qDownload()">Download Order Upload</button>'
      : '<button class="btn primary" disabled>'+
        'Download Order Upload</button>')+
    '</div><div class="cardbody">';
  // The how-to ("edit any cell, only ticked lines are written, this is what the
  // two formats contain") is in the head's marker now. The PO number stays: it
  // is a value, not an explanation.
  // One dropped file can hold several POs. Then the number is a LIST, and the
  // table grows a P/O column (below) so every row says which order it is for.
  const pns = (r.po_numbers && r.po_numbers.length)
    ? r.po_numbers : (r.po_number ? [r.po_number] : []);
  if (pns.length > 1)
    h += '<div class="muted" style="margin-bottom:10px"><b>'+pns.length+
      ' POs</b> in this file - every row keeps its own: '+
      esc(pns.join(', '))+'</div>';
  else if (r.po_number)
    h += '<div class="muted" style="margin-bottom:10px">PO # <b>'+
      esc(r.po_number)+'</b></div>';
  // How many lines are held back because the code is unknown. Said once, above
  // the table, so the amber rows are explained before they are read.
  const nRev = lines.filter(l => l.needs_review).length;
  if (nRev)
    h += '<div class="cardnote" style="margin:0 0 12px; '+
      'border-color:var(--amber); background:var(--amber-soft)">'+
      '<b>'+nRev+' line(s) carry a code that is not in the Material Code '+
      'list.</b> They are shown so nothing disappears, but they are '+
      '<b>unticked and will not be written</b> until you tick them. Check the '+
      'model against the PO, or approve the code on Master Data &gt; '+
      'Material Codes.</div>';
  const nSuffix = lines.filter(l => l.suffix_autofilled).length;
  if (nSuffix)
    h += '<div class="cardnote" style="margin:0 0 12px; '+
      'border-color:var(--amber); background:var(--amber-soft)">'+
      '<b>'+nSuffix+' line(s) had a SKU suffix added automatically.</b> '+
      'The PO code exactly matched the text before one unique FULL SKU '+
      'suffix in Material Code data. These lines are included, but please '+
      '<b>verify the amber correction</b> before downloading.</div>';
  if (!onlySimple) h += qPartyRow();
  // A file holding several POs needs the P/O No. on every row: it is column A
  // of the upload, and two rows with the same model and quantity are otherwise
  // indistinguishable - except that they belong to different orders.
  const showPo = pns.length > 1;
  h += '<table class="qtable"><tr><th style="width:28px"></th>'+
    (showPo ? '<th style="width:110px">P/O No.</th>' : '')+
    '<th>Material Code</th><th>Quantity</th><th>Unit Cost</th><th></th></tr>';
  lines.forEach((l, i) => {
    const on = l.use !== false;
    // needs_review: the code is not in the Material Code list. Shown, amber,
    // and unticked - the line only reaches the ERP file once it is ticked.
    const rv = !!l.needs_review;
    const sf = !!l.suffix_autofilled;
    const warn = !rv && !sf && on && ((l.qty === '' || l.qty === null) ||
                               (l.cost === '' || l.cost === null));
    h += '<tr'+(rv ? ' class="needrow"' :
      (sf ? ' class="fixrow"' : (warn ? ' class="warnrow"' : '')))+
      (on ? '' : ' style="opacity:.55"')+'>'+
      '<td><input type="checkbox" style="width:auto"'+(on?' checked':'')+
        ' title="'+(rv
          ? 'This code is NOT in the Material Code list. Tick to include it '+
            'anyway - check the model against the PO first.'
          : sf
          ? 'A unique SKU suffix was added from Material Code data. This line '+
            'is included; verify the corrected FULL SKU before download.'
          : 'Include in the Order Upload file')+'" '+
        'onchange="qUse('+i+',this.checked)"></td>'+
      // The P/O No. of the order this row was printed on. Only shown when the
      // file holds more than one - otherwise the card's single "PO #" says it.
      (showPo ? '<td class="muted" style="font-size:12px">'+
        esc(l.po || '—')+'</td>' : '')+
      '<td><input type="text" value="'+esc(l.code)+'" '+
        'oninput="qEdit('+i+',\\'code\\',this.value)">'+
        (rv ? '<span class="needpill">not in the code list</span>' : '')+
        (sf ? '<span class="needpill">suffix added — verify</span>' : '')+
        (l.note ? '<div class="fhint">'+esc(l.note)+'</div>' : '')+'</td>'+
      '<td><input type="text" value="'+esc(l.qty)+'" placeholder="—" '+
        'oninput="qEdit('+i+',\\'qty\\',this.value)"></td>'+
      '<td><input type="text" value="'+esc(l.cost)+'" placeholder="—" '+
        'oninput="qEdit('+i+',\\'cost\\',this.value)"></td>'+
      '<td><button class="linkbtn" title="Remove line" '+
        'onclick="qRemoveRow('+i+')">&#10005;</button></td></tr>';
  });
  h += '</table>';
  // "+ Add line" sits under the table rather than in the card head: the head
  // also carries the Full/Simple switch and the Download button, and three
  // controls in one row left no room at 1500px.
  h += '<div style="margin-top:8px">'+
    '<button class="linkbtn" onclick="qAddRow()">+ Add line</button></div>';
  if (r.exportError)
    h += '<div class="cardnote" style="margin-top:12px; '+
      'border-color:var(--danger)"><b>Could not write the Order Upload '+
      'file</b><pre class="qlog" style="margin-top:8px">'+
      esc(r.exportError)+'</pre></div>';
  if (r.downloaded)
    h += '<div class="cardnote" style="margin-top:12px; border-color:#86efac">'+
      '&#10003; Downloaded <b>'+esc(r.downloaded)+'</b>. A copy is kept in '+
      'the data\\\\erp_upload folder.</div>';
  const notes = [];
  if ((r.no_qty||[]).length)
    notes.push('Quantity missing: '+r.no_qty.join(', '));
  if ((r.no_cost||[]).length)
    notes.push('Unit cost missing: '+r.no_cost.join(', '));
  if ((r.unknown||[]).length)
    notes.push('Not in Material Codes, skipped: '+r.unknown.join(', '));
  if ((r.dropped||[]).length)
    notes.push('Unticked — may only be quoted inside another item\\'s '+
      'description: '+r.dropped.join(', ')+'. Tick to include.');
  (r.fixes||[]).forEach(f => notes.push('Corrected — '+f));
  if (notes.length)
    h += '<div class="cardnote" style="margin-top:12px">'+
      notes.map(esc).join('<br>')+'</div>';
  if ((r.messages||[]).length)
    h += '<pre class="qlog">'+esc(r.messages.join('\\n'))+'</pre>';
  return h + '</div></div>';
}

// The folder opens on drag, not on hover. dragenter/dragleave fire again every
// time the pointer crosses one of the folder's own layers, so a plain
// add/remove pair makes the animation stutter and restart; count the nesting
// and shut the folder only when the count is back to zero.
let DRAGDEPTH = 0;
function dropEl(){ return document.getElementById('dropzone'); }
function openDrop(){ const z = dropEl(); if (z) z.classList.add('over'); }
function closeDrop(){
  DRAGDEPTH = 0;
  const z = dropEl(); if (z) z.classList.remove('over');
}
// Dropped or cancelled somewhere else - the folder must not stay open. Bound
// once: the zone is rebuilt on every render, so binding this inside wireDrop()
// would pile up a listener per render.
window.addEventListener('drop', closeDrop, true);
window.addEventListener('dragend', closeDrop, true);

function wireDrop(){
  const dz = document.getElementById('dropzone');
  if (!dz) return;

  dz.addEventListener('dragenter', ev => {
    ev.preventDefault(); DRAGDEPTH++; openDrop();
  });
  dz.addEventListener('dragover', ev => {
    ev.preventDefault();
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'copy';
    openDrop();
  });
  dz.addEventListener('dragleave', ev => {
    ev.preventDefault();
    DRAGDEPTH = Math.max(0, DRAGDEPTH - 1);
    if (!DRAGDEPTH){
      const z = dropEl(); if (z) z.classList.remove('over');
    }
  });
  dz.addEventListener('drop', ev => {
    ev.preventDefault();
    closeDrop();
    qPick(ev.dataTransfer.files);
  });

  // The folder itself is the obvious thing to click, so it opens the picker.
  const fold = document.getElementById('dzfold');
  if (fold){
    const pick = () => { const f = document.getElementById('qfile'); if (f) f.click(); };
    fold.addEventListener('click', pick);
    fold.addEventListener('keydown', ev => {
      if (ev.key === 'Enter' || ev.key === ' '){ ev.preventDefault(); pick(); }
    });
  }
}

function qPick(files){
  const list = Array.from(files || []);
  if (!list.length) return;
  // Dropping a new file starts a new conversion - the old result would
  // otherwise sit there looking like it belongs to the file just added.
  QRESULT = null;
  let left = list.length;
  list.forEach(f => {
    const fr = new FileReader();
    fr.onload = () => {
      QFILES.push({name: f.name, size: f.size,
        data: fr.result.split(',')[1]});
      if (--left === 0) render();
    };
    fr.onerror = () => { if (--left === 0) render(); };
    fr.readAsDataURL(f);
  });
}

function qRemove(i){ QFILES.splice(i, 1); render(); }
function qClear(){ QFILES = []; QSEL = []; QRESULT = null; render(); }

async function qConvert(){
  const n = QSEL.length + QFILES.length;
  if (!n) return;
  toast('Reading '+n+' file(s)…');
  const names = QSEL.map(p => p.split(/[\\\\/]/).pop())
    .concat(QFILES.map(f => f.name)).join(', ');
  // The folder box goes too: a dropped file arrives without a path, and if
  // it turns out to be DRM-protected the server can only read the original
  // by finding that name in a folder we already know about.
  const r = await api('/api/quick_convert',
    {files: QFILES, paths: QSEL.join('\\n'),
     folder: (document.getElementById('q-folder')||{}).value || ''});
  r.source = names;
  QRESULT = r;
  render();
  if (!r.error) toast((r.lines||[]).length+' line(s) found — review below');
}

// Edits are kept in QRESULT.lines; the table is not re-rendered on every
// keystroke so the cursor stays put.
function qEdit(i, field, value){
  if (!QRESULT || !QRESULT.lines[i]) return;
  QRESULT.lines[i][field] = value.trim();
}
function qUse(i, on){
  if (!QRESULT || !QRESULT.lines[i]) return;
  QRESULT.lines[i].use = on;
  render();
}
function qRemoveRow(i){
  if (!QRESULT) return;
  QRESULT.lines.splice(i, 1);
  render();
}
function qAddRow(){
  if (!QRESULT) QRESULT = {lines: []};
  QRESULT.lines.push({code:'', qty:'', cost:'', use:true});
  render();
}

async function qDownload(){
  if (!QRESULT) return;
  const lines = (QRESULT.lines||[]).filter(l =>
    l.use !== false && (l.code||'').trim());
  if (!lines.length){ alert('There is no ticked line with a Material Code.'); return; }
  const missing = lines.filter(l => l.qty === '' || l.cost === '').length;
  if (missing && !confirm(missing+' line(s) have no quantity or unit cost. '+
      'Those cells will be left blank in the file.\\n\\nDownload anyway?'))
    return;
  // Everything ticked on the switch, in one request: the lines are already
  // reviewed, so writing a second file costs nothing but the write.
  const want = erpFmts();
  toast(want.length > 1 ? 'Building '+want.length+' Order Upload files…'
                        : 'Building Order Upload file…');
  const r = await api('/api/quick_export',
    {lines: lines, tag: QRESULT.po_number || '',
     po: QRESULT.po_number || '', format: want,
     sold_to: QPARTY.sold_to, ship_to: QPARTY.ship_to,
     // `ship` is what the user typed; `order` is what the PO printed for the
     // whole order (dates + delivery address). The server layers them, typed
     // first - so an empty card box still produces a filled ERP cell.
     ship: QPARTY.ship, order: QRESULT.order || null});
  if (r.error){
    // Keep the extracted lines on screen - the problem is the ERP template,
    // not the data the user just reviewed.
    QRESULT.exportError = r.error;
    render();
    return;
  }
  QRESULT.exportError = '';
  // Trigger a browser download for EVERY file written; they also stay under
  // data/erp_upload. A browser may only keep the last of several automatic
  // downloads, which is why the Output card below lists both as real links.
  const made = (r.files || []).filter(f => f && f.url);
  made.forEach(f => {
    const a = document.createElement('a');
    a.href = f.url; a.download = f.name;
    document.body.appendChild(a); a.click(); a.remove();
  });

  // Record it and reset, so the next PO can be dropped straight away.
  QDONE.unshift({source: QRESULT.source || '(files)', po: QRESULT.po_number,
    count: r.count, name: r.name, url: r.url,
    fmt: want.length > 1 ? want.join('+') : want[0],
    fmts: want, files: made,
    customer: QPARTY.customer, sold_to: QPARTY.sold_to, ship_to: QPARTY.ship_to,
    lines: JSON.parse(JSON.stringify(lines)), messages: QRESULT.messages});
  QFILES = []; QSEL = []; QRESULT = null;
  render();
  toast(made.length > 1
    ? made.length+' files written — ready for the next file'
    : r.count+' line(s) written — ready for the next file');
  window.scrollTo({top: 0, behavior: 'smooth'});
}

// ── Quick Convert: Domain / Sold-To / Ship-To ──
// Quick Convert has no mail row to take the account numbers from, so they are
// chosen on the review card. Picking the domain narrows the other two to the
// (Sold-To, Ship-To) pairs that domain owns in the Ship-To master.
// `ship` holds the Ship-To block typed on the review card - the same
// twelve per-order fields the Inbox row carries (N, O-Q, R, S-V, W, X, AZ).
let QPARTY = {customer: '', sold_to: '', ship_to: '', ship: {}};

// One of the two account boxes on the review card. Same component as the Inbox
// rows, in `quick` mode: committing calls qPartySet() instead of saving to a
// mail row. A card with no domain chosen yet (or whose domain is still being
// fetched) gets a disabled box saying which of the two it is waiting for.
function qPartyCombo(kind, domain, known, loaded, value, idle){
  if (!known || !loaded)
    return '<input class="pcinput" type="text" disabled '+
      'placeholder="'+esc(known ? 'loading…' : idle)+'">';
  return comboHTML({kind: kind, domain: domain, quick: true, value: value,
                    sold: kind === 'ship' ? QPARTY.sold_to : ''});
}

function qPartyRow(){
  const names = (DATA.master || []).map(x => x.customer).slice().sort();
  const c = QPARTY.customer;
  const p = c ? PARTY[c] : null;
  const known = !!(c && domainKnown(c));
  let h = '<div class="prow">'+
    '<label>Domain <select onchange="qPartyDomain(this.value)">'+
    '<option value="">— none —</option>';
  for (const n of names)
    h += '<option value="'+esc(n)+'"'+(n === c ? ' selected' : '')+'>'+
      esc(n)+'</option>';
  h += '</select></label>';
  // The same searchable box the Inbox rows use - a customer with thousands of
  // sites cannot be picked from a <select> here either, and the card has even
  // less room for one. `known` is "the master knows this domain"; without it
  // there is nothing to offer and the box says what to do first.
  h += '<label>Sold-To-Party '+qPartyCombo('sold', c, known, p,
      QPARTY.sold_to, '— pick a domain first —')+'</label>';
  h += '<label>Ship-To-Party '+qPartyCombo('ship', c, known, p,
      QPARTY.ship_to, '—')+'</label>';
  const ch = c ? partyChannel(c, QPARTY.ship_to, QPARTY.sold_to) : '';
  h += '<span class="chnchip'+(ch ? ' set' : '')+'" title="Column D of the '+
    'full form — from the TYPE on this (Sold-To, Ship-To) row">'+
    (ch ? 'Distr. Channel '+esc(ch) : 'Distr. Channel —')+'</span>';
  h += '</div>';
  // The Ship-To block, same shape as the Inbox row: N and R in the open, the
  // other ten behind a disclosure. It is here as well because this card builds
  // an ERP file too - leaving it out would send that file with no address at
  // all, which is worse than the master-derived address it replaced.
  const nameHit = masterShipHit(c, QPARTY.ship_to, QPARTY.sold_to);
  const nameDef = (nameHit && nameHit.name) || '';
  h += '<div class="qship">';
  h += '<label>Ship-to Name'+
    '<input type="text" id="q-ship_to_name" value="'+
      esc(QPARTY.ship.ship_to_name || '')+'" placeholder="'+esc(nameDef)+'" '+
      'oninput="qShipField(\\'ship_to_name\\', this.value)"></label>';
  h += '<label>Ship-to Address'+
    '<input type="text" id="q-ship_to_address" value="'+
      esc(QPARTY.ship.ship_to_address || '')+'" '+
      'placeholder="delivery street address" '+
      'oninput="qShipField(\\'ship_to_address\\', this.value)"></label>';
  // The two dates, with what the PO printed as the placeholder - so the user
  // sees the value that will be written and only has to type when overriding
  // it. An empty box is NOT "blank the cell": it means "use the document's".
  const ord = (QRESULT && QRESULT.order) || {};
  const rddNote = ord.rdd_defaulted
    ? 'default — 6 working days after the PO date'
    : '';
  h += '<div class="qdates">';
  h += '<label>PO date (M)'+
    '<input type="date" value="'+esc(QPARTY.ship.po_date || '')+'" '+
      'placeholder="'+esc(ord.po_date || '')+'" '+
      'title="Column M. Blank uses the date printed on the PO'+
      (ord.po_date ? ' (' + esc(ord.po_date) + ')' : '')+'." '+
      'oninput="qShipField(\\'po_date\\', this.value)"></label>';
  h += '<label>R.D.D (K)'+(rddNote ? faq('rdd') : '')+
    '<input type="date" value="'+esc(QPARTY.ship.rdd || '')+'" '+
      'placeholder="'+esc(ord.rdd || '')+'" '+
      'title="Column K, the required delivery date. Blank uses '+
      (ord.rdd ? esc(ord.rdd) + (rddNote ? ' ('+rddNote+')' : '') :
                 'PO date + 6 working days')+'." '+
      'oninput="qShipField(\\'rdd\\', this.value)"></label>';
  h += '</div>';
  h += '<details class="shipmore"><summary>More ship-to fields</summary>'+
    '<div class="shipgrid">';
  SHIP_MORE.forEach(f => {
    if (ORDER_FIELDS.indexOf(f[0]) >= 0) return;   // rendered above
    h += '<label>'+esc(f[1])+shipQuickInput(f[0], f[2])+'</label>';
  });
  h += '</div></details></div>';
  return h;
}


// One folded field on the Quick Convert card.
function shipQuickInput(key, kind){
  const v = QPARTY.ship[key] || '';
  if (kind === 'state'){
    let opts = '<option value="">—</option>';
    shipStates().forEach(s => {
      opts += '<option value="'+esc(s)+'"'+(s === v ? ' selected' : '')+'>'+
        esc(s)+'</option>';
    });
    return '<select oninput="qShipField(\\''+key+'\\', this.value)" '+
      'onchange="qShipField(\\''+key+'\\', this.value)">'+opts+'</select>';
  }
  return '<input type="text" value="'+esc(v)+'" '+
    'oninput="qShipField(\\''+key+'\\', this.value)">';
}

function qShipField(key, value){
  QPARTY.ship[key] = (value || '').trim();
}

async function qPartyDomain(name){
  QPARTY.customer = name;
  QPARTY.sold_to = '';
  QPARTY.ship_to = '';
  QPARTY.ship = {};      // a different customer is a different delivery
  if (name && !PARTY[name] && domainKnown(name)){
    render();                             // show the "loading" state
    PARTY[name] = await api('/api/party_options', {domain: name, role: ''})
      .catch(() => ({sold_tos: [], ship_tos: []}));
  }
  render();
}

// What the two account boxes on the review card write to, once the user picks
// a candidate or types a number. `render()` re-draws the card, so the popup has
// to go first: it is anchored to an element that is about to be replaced.
function qPartySet(kind, value){
  pcClose();
  if (kind === 'sold') QPARTY.sold_to = value;
  else QPARTY.ship_to = value;
  render();
}

// ── Ship-To Locations: the master, and it is editable ──
// This is the ONLY customer data there is. One row = one (Sold-To, Ship-To)
// pair; column C, the domain, is the identity every mail is matched by. The
// table runs to thousands of rows, so the server sends one window at a time,
// and every edit addresses its row by the `_i` the server handed out - which
// is the row's position in the STORED table, not in the window.
let SHIP = {rows: [], total: 0, offset: 0, q: ''};
let SHIPT = null;                  // search debounce timer
const SHIPLIMIT = 100;

// The DOMAIN table: the second half of the customer data, a separate file with
// its own grid. One row per customer name, joined to the pair table by
// SOLD_TO_NAME at read time - which is why editing it here changes which mail
// gets a customer, without touching a single pair row.
let DOM = {rows: [], total: 0, offset: 0, q: ''};
let DOMT = null;
const DOMLIMIT = 200;

// A pair is flagged red when the master lists it twice with details that
// disagree: the export refuses to guess those, so all six ERP cells stay empty
// and only the user can decide which copy is right.
function shipConfSet(){
  const set = {};
  (DATA.ship_conflicts || []).forEach(k => { set[k] = true; });
  return set;
}

async function loadShip(){
  const box = document.getElementById('shipbody');
  if (box) box.innerHTML = '<div class="shipmsg">Loading…</div>';
  const r = await api('/api/master_rows',
    {q: SHIP.q, limit: SHIPLIMIT, offset: SHIP.offset});
  SHIP.rows = (r && r.rows) || [];
  SHIP.total = (r && r.total) || 0;
  const el = document.getElementById('shipbody');
  if (el) el.innerHTML = shipTable();
  shipCount();
}

function shipCount(){
  const c = document.getElementById('shipcount');
  if (!c) return;
  if (!SHIP.total){ c.textContent = 'no rows'; return; }
  const to = Math.min(SHIP.offset + SHIPLIMIT, SHIP.total);
  c.textContent = 'showing '+(SHIP.offset + 1)+'–'+to+' of '+SHIP.total+
    ' row(s)';
}

function shipSearch(v){
  SHIP.q = v;
  SHIP.offset = 0;
  clearTimeout(SHIPT);
  SHIPT = setTimeout(loadShip, 250);
}

function shipClear(){
  const el = document.getElementById('shipq');
  if (el) el.value = '';
  shipSearch('');
}

function shipPage(dir){
  const next = SHIP.offset + dir * SHIPLIMIT;
  if (next < 0 || next >= SHIP.total) return;
  SHIP.offset = next;
  loadShip();
}

function shipTable(){
  const cols = (DATA.ship_columns || []);
  if (!cols.length)
    return '<div class="shipmsg">The server sent no column list.</div>';
  if (!SHIP.rows.length)
    return '<div class="shipmsg">'+(SHIP.q
      ? 'No row matches "'+esc(SHIP.q)+'".'
      : 'The table is empty. Upload the ERP Ship To Locations export, or use '+
        '+ Add row.')+'</div>';
  const conf = shipConfSet();
  let h = '<div class="shipwrap"><table class="shiptable"><tr><th>#</th>';
  cols.forEach(c => {
    h += '<th title="'+esc(c.title || c.header)+'" style="min-width:'+
      Math.max(88, Math.round((c.width || 14) * 5.4))+'px">'+
      esc(c.header)+'</th>';
  });
  h += '<th></th></tr>';
  SHIP.rows.forEach(r => {
    const bad = !!conf[(r.sold_to_code || '') + '|' + (r.ship_to_code || '')];
    h += '<tr'+(bad ? ' class="shipconf"' : '')+'>'+
      '<td class="shipno">'+r._i+'</td>';
    cols.forEach(c => {
      const v = r[c.key] || '';
      h += '<td><input class="scell" value="'+esc(v)+'" '+
        'data-i="'+r._i+'" data-k="'+esc(c.key)+'" title="'+esc(v)+'" '+
        'onchange="setShipCell(this)"></td>';
    });
    h += '<td><button class="linkbtn" title="Delete this row" '+
      'onclick="delShipRow('+r._i+')">&#10005;</button></td></tr>';
  });
  return h + '</table></div>'+
    (Object.keys(conf).length
      ? '<div class="shiplegend">Red rows: the (Sold-To, Ship-To) pair is '+
        'listed more than once with different details. The ERP columns are '+
        'left EMPTY for those until one copy is fixed.</div>'
      : '');
}

async function setShipCell(el){
  const i = +el.dataset.i, k = el.dataset.k, v = el.value.trim();
  const r = await api('/api/master_set', {index: i, key: k, value: v});
  if (r && r.error){ alert(r.error); return; }
  forgetParty();
  el.title = v;
  if (r && r.conflicts) DATA.ship_conflicts = r.conflicts;
  const row = SHIP.rows.find(x => x._i === i);
  if (row){
    row[k] = v;
    const tr = el.closest('tr');
    if (tr) tr.classList.toggle('shipconf',
      !!shipConfSet()[(row.sold_to_code || '') + '|' + (row.ship_to_code || '')]);
  }
}

async function addShipRow(){
  const r = await api('/api/master_add', {blank: true});
  if (r.error){ alert(r.error); return; }
  forgetParty();
  const el = document.getElementById('shipq');
  if (el) el.value = '';
  SHIP.q = '';
  // Jump to the window the new row landed in, then put the cursor on it.
  SHIP.offset = Math.floor(r.index / SHIPLIMIT) * SHIPLIMIT;
  await loadShip();
  const first = document.querySelector('#shipbody input[data-i="'+r.index+'"]');
  if (first) first.focus();
  toast('Row added — fill in the Sold-To / Ship-To codes and the customer name');
}

async function delShipRow(i){
  if (!confirm('Delete row #'+i+'?\\n\\nThe (Sold-To, Ship-To) pair leaves '+
      'the master, so orders can no longer fill the ERP columns from it.'))
    return;
  const r = await api('/api/master_del', {index: i});
  if (r.error){ alert(r.error); return; }
  forgetParty();
  await load();
  toast('Row deleted');
}

async function clearShipMaster(){
  const n = (DATA.erp || {}).total || 0;
  if (!n){ toast('The table is already empty'); return; }
  // This clears BOTH tables - the pair table and the domain table - because
  // leaving the domains behind would look like the clear failed.
  if (!confirm('Delete ALL '+n+' Ship-To row(s) AND every domain row?\\n\\n'+
      'Every stored mail loses its customer until both tables are uploaded '+
      'again. There is no undo.')) return;
  if (!confirm('Really delete all rows of both tables?')) return;
  const r = await api('/api/master_clear', {});
  if (r.error){ alert(r.error); return; }
  forgetParty();
  SHIP.offset = 0;
  DOM.offset = 0;
  await load();
  toast('Customer data cleared ('+(r.removed || 0)+' rows in total)');
}

// ── The file picker (Data screens) ───────────────────────────────────────
// The browser's own file control cannot be styled, so it reads as a grey form
// leftover in the middle of a designed card. It is still the thing that does
// the work: it stays in the DOM, hidden, and the button only forwards the click
// to it. Three layers - back, sheet, cover - so the hover can lift the sheet and
// tip the cover, the same gesture the Quick Convert drop folder uses.
const DOC_FOLDER =
  // Three layers, each with its own tight viewBox and a size in px, so the
  // geometry in the comment below is the geometry on screen: back y2-26,
  // sheet y5-20, cover y12.5-26 in a 30x26 box.
  '<svg class="fileBack" viewBox="0 0 30 24" aria-hidden="true">'+
    '<path d="M0 3a3 3 0 0 1 3-3h9l3 3h12a3 3 0 0 1 3 3v15a3 3 0 0 1-3 3H3a3 3 '+
    '0 0 1-3-3z" fill="#b45309"/></svg>'+
  '<svg class="filePage" viewBox="0 0 16 15" aria-hidden="true">'+
    '<rect x="0" y="0" width="16" height="15" rx="2" fill="#ffffff"/>'+
    '<rect x="3" y="2.2" width="10" height="1.6" rx=".8" fill="#cbd5e1"/>'+
    '<rect x="3" y="5" width="10" height="1.6" rx=".8" fill="#cbd5e1"/>'+
    '<rect x="3" y="7.8" width="6" height="1.6" rx=".8" fill="#cbd5e1"/>'+
  '</svg>'+
  '<svg class="fileFront" viewBox="0 0 30 14" aria-hidden="true">'+
    '<path d="M0 0h30v10a4 4 0 0 1-4 4H4a4 4 0 0 1-4-4z" fill="#fbbf24"/>'+
    '<path d="M0 0h30v2.4H0z" fill="#fcd34d"/>'+
  '</svg>';

// The label is the initial instruction, and it becomes the chosen file's name -
// the native control showed that, and losing it would make "did I pick the
// right sheet" unanswerable without opening the picker again.
function docPick(id, label){
  return '<span class="docpick">'+
    '<button type="button" class="docbtn" onclick="pickDoc(\\''+id+'\\')">'+
      '<span class="folderContainer">'+DOC_FOLDER+'</span>'+
      '<span class="doctext" id="'+id+'-name">'+
        esc(label || 'Choose file')+'</span>'+
    '</button>'+
    '<input type="file" id="'+id+'" accept=".xlsx,.xlsm,.xls" hidden '+
      'onchange="docPicked(this)">'+
  '</span>';
}

function pickDoc(id){
  const f = document.getElementById(id);
  if (f) f.click();
}

function docPicked(inp){
  const name = document.getElementById(inp.id + '-name');
  if (!name) return;
  const f = inp.files && inp.files[0];
  name.textContent = f ? f.name : 'Choose file';
  name.title = f ? f.name : '';
  name.classList.toggle('has', !!f);
}

function uploadErp(){
  const f = document.getElementById('erp-file').files[0];
  if (!f){ alert('Choose the ERP Ship To Locations file first.'); return; }
  const n = (DATA.erp || {}).total || 0;
  if (n && !confirm('Replace all '+n+' stored row(s) with '+f.name+'?\\n\\n'+
      'Rows the file does not contain are removed.')) return;
  const fr = new FileReader();
  fr.onload = async () => {
    toast('Reading the Ship-To master…');
    const r = await api('/api/erp_upload',
      {filename: f.name, data: fr.result.split(',')[1]});
    if (r.error){ alert(r.error); return; }
    forgetParty();
    let m = 'Read '+r.rows+' row(s).\\n\\n'+
      'Domains (the identity): '+r.domains+'\\n'+
      'Sold-To codes: '+r.sold_tos+'\\n'+
      'Ship-To codes: '+r.ship_tos+'\\n\\nTypes: '+Object.keys(r.types || {})
        .sort().map(k => k+' '+r.types[k]).join(', ');
    if (r.conflict_count){
      m += '\\n\\n'+r.conflict_count+' (Sold-To, Ship-To) pair(s) appear more '+
        'than once with DIFFERENT details. Those rows are marked red and stay '+
        'EMPTY in the ERP columns until one copy is fixed:';
      (r.conflicts || []).forEach(c => {
        m += '\\n  '+c.sold_to+' / '+c.ship_to+'  ('+c.rows+' rows)'; });
    }
    alert(m);
    SHIP.offset = 0;
    await load();
  };
  fr.readAsDataURL(f);
}

// ── the DOMAIN table: its own grid, its own upload, its own export ─────────
// Mirrors the Ship-To grid above against the domain_row_* endpoints. The names
// deliberately avoid the two the retired member model used to own (see the
// 2026-10 refactor in the handover): reusing them would look like the old
// card-claim API coming back.
// Nothing here reads or writes a pair row: the two tables meet only through
// the customer name, which the server resolves.

async function loadDom(){
  const box = document.getElementById('dombody');
  if (box) box.innerHTML = '<div class="shipmsg">Loading…</div>';
  const r = await api('/api/domain_row_list',
    {q: DOM.q, limit: DOMLIMIT, offset: DOM.offset});
  DOM.rows = (r && r.rows) || [];
  DOM.total = (r && r.total) || 0;
  const el = document.getElementById('dombody');
  if (el) el.innerHTML = domTable();
  domCount();
}

function domCount(){
  const c = document.getElementById('domcount');
  if (!c) return;
  if (!DOM.total){ c.textContent = 'no rows'; return; }
  const to = Math.min(DOM.offset + DOMLIMIT, DOM.total);
  c.textContent = 'showing '+(DOM.offset + 1)+'–'+to+' of '+DOM.total+
    ' row(s)';
}

function domSearch(v){
  DOM.q = v;
  DOM.offset = 0;
  clearTimeout(DOMT);
  DOMT = setTimeout(loadDom, 250);
}

function domClear(){
  const el = document.getElementById('domq');
  if (el) el.value = '';
  domSearch('');
}

function domPage(dir){
  const next = DOM.offset + dir * DOMLIMIT;
  if (next < 0 || next >= DOM.total) return;
  DOM.offset = next;
  loadDom();
}

function domTable(){
  const cols = (DATA.domain_columns || []);
  if (!cols.length)
    return '<div class="shipmsg">The server sent no column list.</div>';
  if (!DOM.rows.length)
    return '<div class="shipmsg">'+(DOM.q
      ? 'No row matches "'+esc(DOM.q)+'".'
      : 'The table is empty. Upload the domain sheet from the ERP file, or '+
        'use + Add row. Until it has rows, no mail can be matched to a '+''+
        'customer.')+'</div>';
  let h = '<div class="shipwrap"><table class="shiptable"><tr><th>#</th>';
  cols.forEach(c => {
    h += '<th title="'+esc(c.title || c.header)+'" style="min-width:'+
      Math.max(88, Math.round((c.width || 14) * 5.4))+'px">'+
      esc(c.header)+'</th>';
  });
  h += '<th></th></tr>';
  DOM.rows.forEach(r => {
    h += '<tr><td class="shipno">'+r._i+'</td>';
    cols.forEach(c => {
      const v = r[c.key] || '';
      h += '<td><input class="scell" value="'+esc(v)+'" '+
        'data-i="'+r._i+'" data-k="'+esc(c.key)+'" title="'+esc(v)+'" '+
        'onchange="setDomCell(this)"></td>';
    });
    h += '<td><button class="linkbtn" title="Delete this row" '+
      'onclick="delDomRow('+r._i+')">&#10005;</button></td></tr>';
  });
  return h + '</table></div>'+
    '<div class="shiplegend">One row per customer name. The <b>name</b> is '+
    'what joins this table to the Ship-To table; the <b>domain</b> is what '+
    'mail is matched by. Spelling differences in the name are tolerated.</div>';
}

async function setDomCell(el){
  const i = +el.dataset.i, k = el.dataset.k, v = el.value.trim();
  const r = await api('/api/domain_row_set', {index: i, key: k, value: v});
  if (r && r.error){ alert(r.error); return; }
  el.title = v;
  const row = DOM.rows.find(x => x._i === i);
  if (row) row[k] = v;
  // The server has also reclassified stored mail. Wait for the identity and
  // account caches, then pull those changed mail rows now; switching straight
  // back to Inbox must not show the pre-edit dashboard until the next poll.
  await forgetParty();
  await load();
}

async function addDomRow(){
  const r = await api('/api/domain_row_add', {blank: true});
  if (r.error){ alert(r.error); return; }
  forgetParty();
  const el = document.getElementById('domq');
  if (el) el.value = '';
  DOM.q = '';
  DOM.offset = Math.floor(r.index / DOMLIMIT) * DOMLIMIT;
  await loadDom();
  const first = document.querySelector('#dombody input[data-i="'+r.index+'"]');
  if (first) first.focus();
  toast('Row added — fill in the customer name and its domain');
}

async function delDomRow(i){
  if (!confirm('Delete domain row #'+i+'?\\n\\nEvery stored mail from that '+
      'domain loses its customer until the row is added back.')) return;
  const r = await api('/api/domain_row_del', {index: i});
  if (r.error){ alert(r.error); return; }
  await forgetParty();
  await load();
  toast('Domain row deleted');
}

async function clearDomTable(){
  const n = ((DATA.domain_status || {}).total) || 0;
  if (!n){ toast('The table is already empty'); return; }
  if (!confirm('Delete ALL '+n+' domain row(s)?\\n\\nThe Ship-To table is '+
      'kept, but with no domain table every mail comes back unclassified. '+
      'There is no undo.')) return;
  if (!confirm('Really delete all '+n+' domain rows?')) return;
  const r = await api('/api/domain_row_clear', {});
  if (r.error){ alert(r.error); return; }
  await forgetParty();
  DOM.offset = 0;
  await load();
  toast('Domain table cleared ('+(r.removed || 0)+' rows)');
}

function uploadDomains(){
  const f = document.getElementById('dom-file').files[0];
  if (!f){ alert('Choose the domain file first.'); return; }
  const n = ((DATA.domain_status || {}).total) || 0;
  if (n && !confirm('Replace all '+n+' stored domain row(s) with '+f.name+
      '?\\n\\nRows the file does not contain are removed.')) return;
  const fr = new FileReader();
  fr.onload = async () => {
    toast('Reading the domain table…');
    const r = await api('/api/domain_table_upload',
      {filename: f.name, data: fr.result.split(',')[1]});
    if (r.error){ alert(r.error); return; }
    await forgetParty();
    let m = 'Read '+r.rows+' row(s).\\n\\n'+
      'Distinct domains: '+r.domains+'\\n'+
      'Customer names: '+r.named;
    if (r.unmatched_names){
      m += '\\n\\n⚠️ '+r.unmatched_names+' Ship-To name(s) are NOT in this '+
        'file, so those pairs have no customer and their mail stays '+
        'unclassified until a row is added.';
    }
    alert(m);
    DOM.offset = 0;
    await load();
  };
  fr.readAsDataURL(f);
}

function renderMaster(){
  const e = DATA.erp || {};
  const d = DATA.domain_status || {};
  let h = '<div class="applybar"><div style="font-weight:600; '+
    'font-size:13.5px">Customer data'+faq('master')+'</div>'+
    '<div style="display:flex; gap:8px">'+
    '<button class="btn" onclick="addShipRow()">+ Add pair row</button>'+
    '<button class="btn" onclick="addDomRow()">+ Add domain row</button>'+
    '<button class="btn" onclick="applyMaster()">Re-match stored mail</button>'+
    '<button class="btn" onclick="clearShipMaster()">Clear all</button>'+
    '</div></div>';

  let sub;
  if (e.total){
    sub = '<b>'+e.total+'</b> rows from <b>'+esc(e.source_file || '')+
      '</b> ('+fmtDT(e.uploaded_at)+') — <b>'+e.domains+'</b> domains, '+
      e.sold_tos+' Sold-To, '+e.ship_tos+' Ship-To';
    if (e.conflict_count)
      sub += ' · <span class="shipwarntxt">'+e.conflict_count+
        ' conflicting pair(s)</span>';
  } else {
    sub = '<span class="muted">No Ship-To master yet. Upload the ERP '+
      '<b>Ship To Locations</b> export to build it.</span>';
  }
  h += '<div class="card setcard"><div class="cardhead">'+
    '<h3>Ship-To locations — upload'+faq('mastership')+'</h3></div>'+
    '<div class="setbody">'+
    '<p style="margin:0 0 14px">'+sub+'</p>'+
    '<div class="frow"><label>File</label><div class="fctl">'+
    docPick('erp-file', 'Choose the Ship-To workbook')+
    '</div></div><div class="setactions"><div class="spacer"></div>'+
    '<button class="btn primary" onclick="uploadErp()">Upload &amp; '+
    'rebuild</button></div></div></div>';

  // -- the DOMAIN table: its own upload card and its own grid --------------
  let dsub;
  if (d.total){
    dsub = '<b>'+d.total+'</b> rows from <b>'+esc(d.source_file || '')+
      '</b> ('+fmtDT(d.uploaded_at)+') — <b>'+d.domains+'</b> distinct domains';
  } else {
    dsub = '<span class="muted">No domain table yet. Upload the domain '+
      'sheet from the ERP file (its second sheet: <b>SOLD_TO_NAME</b> and '+
      '<b>DOMAIN</b>), or add the rows by hand below. Until it has rows, no '+
      'mail can be matched to a customer.</span>';
  }
  h += '<div class="card setcard"><div class="cardhead">'+
    '<h3>Domains — upload'+faq('masterdom')+'</h3></div>'+
    '<div class="setbody">'+
    '<p style="margin:0 0 14px">'+dsub+'</p>'+
    '<div class="frow"><label>File</label><div class="fctl">'+
    docPick('dom-file', 'Choose the domain sheet')+
    '</div></div><div class="setactions"><div class="spacer"></div>'+
    '<button class="btn primary" onclick="uploadDomains()">Upload &amp; '+
    'rebuild</button></div></div></div>';

  const q = (SHIP.q || '').trim();
  h += '<div class="card"><div class="cardhead"><h3>Ship-To locations</h3>'+
    '<span class="count" id="shipcount"></span></div>'+
    '<div class="setbody"><div class="inline">'+
    '<input type="text" id="shipq" placeholder="Search Sold-To or '+
    'Ship-To code / name" value="'+esc(q)+'" oninput="shipSearch(this.value)" '+
    'style="max-width:340px">'+
    (q ? '<button class="btn" onclick="shipClear()">Clear</button>' : '')+
    '<span class="spacer" style="flex:1"></span>'+
    '<button class="btn" onclick="shipPage(-1)">&larr; Prev</button>'+
    '<button class="btn" onclick="shipPage(1)">Next &rarr;</button>'+
    exportSplit({id: 'cust', set: 'customers', label: 'Export',
      canFilter: SHIP.total > 0,
      filterHint: q ? SHIP.total+' matching "'+q+'"'
                    : 'search for something first',
      title: 'Download the Ship-To master as the upload file'})+
    '</div></div>'+
    '<div id="shipbody" class="shipbody"><div class="shipmsg">Loading…</div>'+
    '</div></div>';

  // -- the domain grid -----------------------------------------------------
  const dq = (DOM.q || '').trim();
  h += '<div class="card"><div class="cardhead"><h3>Domains</h3>'+
    '<span class="count" id="domcount"></span></div>'+
    '<div class="setbody"><div class="inline">'+
    '<input type="text" id="domq" placeholder="Search customer name or '+
    'domain" value="'+esc(dq)+'" oninput="domSearch(this.value)" '+
    'style="max-width:340px">'+
    (dq ? '<button class="btn" onclick="domClear()">Clear</button>' : '')+
    '<span class="spacer" style="flex:1"></span>'+
    '<button class="btn" onclick="domPage(-1)">&larr; Prev</button>'+
    '<button class="btn" onclick="domPage(1)">Next &rarr;</button>'+
    '<button class="btn" onclick="clearDomTable()">Clear all</button>'+
    exportSplit({id: 'dom', set: 'domains', label: 'Export',
      canFilter: DOM.total > 0,
      filterHint: dq ? DOM.total+' matching "'+dq+'"'
                    : 'search for something first',
      title: 'Download the domain table as the upload file'})+
    '</div></div>'+
    '<div id="dombody" class="shipbody"><div class="shipmsg">Loading…</div>'+
    '</div></div>';

  h += renderUnmatchedSection();
  return h;
}

let CODES = null, CODEQ = '', CODECAT = '', CODESORT = 'cat';
let OPEN = {};   // Products expanded in the tree
let CODET = null;   // search debounce timer (same shape as SHIPT / DOMT)

// Only the tree body is rebuilt when the filter or a fold changes. The whole
// page used to be re-rendered here, which tore the search box out of the
// document - so the SECOND character of a query could not be typed at all.
// The input is now outside the replaced region and is never touched.
function refreshCodeTree(){
  const tree = document.getElementById('codetree');
  if (!tree) { render(); return; }
  tree.innerHTML = codesTreeHTML(shownCodes());
  const cnt = document.getElementById('codecount');
  if (cnt && CODES && CODES.materials)
    cnt.textContent = shownCodes().length + ' of ' + CODES.materials.length;
}

function setCodeQ(v){
  CODEQ = (v || '');
  clearTimeout(CODET);
  CODET = setTimeout(refreshCodeTree, 180);
}

// The Product > Type 1 > Type 2 > code grid. Reads CODEQ/CODECAT itself so it
// can be rebuilt on its own; `shown` is passed in so renderCodes and this
// function cannot drift apart on what "the filter" means.
function codesTreeHTML(shown){
  const q = (CODEQ || '').trim().toUpperCase();
  const tree = {};
  for (const c of shown){
    const p = c.product || '(uncategorised)';
    const t1 = c.cate1 || '';
    const t2 = c.cate2 || '';
    ((tree[p] = tree[p] || {})[t1] = tree[p][t1] || {})[t2] =
      (tree[p][t1][t2] || []).concat([c]);
  }
  const searching = !!q;
  let h = '';
  if (!shown.length){
    return '<div class="cardnote">No codes'+((q||CODECAT)?' match this filter':
      ' yet — upload a price sheet above')+'.</div>';
  }
  for (const p of Object.keys(tree).sort()){
    const t1s = tree[p];
    let pn = 0;
    for (const t1 in t1s) for (const t2 in t1s[t1]) pn += t1s[t1][t2].length;
    const open = searching || OPEN[p];
    h += '<div class="tnode" onclick="toggleNode('+
      JSON.stringify(p).replace(/"/g,'&quot;')+')">'+
      '<i class="tcar">'+(open?'&#9662;':'&#9656;')+'</i>'+
      '<span class="tname">'+esc(p)+'</span>'+
      '<span class="tcount">'+pn+(pn===1?' code':' codes')+
      '</span></div>';
    if (!open) continue;
    h += '<div class="tbranch">';
    for (const t1 of Object.keys(t1s).sort()){
      const t2s = t1s[t1];
      let n1 = 0;
      for (const t2 in t2s) n1 += t2s[t2].length;
      if (t1) h += '<div class="tsub"><span class="tname2">'+esc(t1)+
        '</span><span class="tcount">'+n1+'</span></div>';
      for (const t2 of Object.keys(t2s).sort()){
        if (t2) h += '<div class="ttype2"><span class="t2chip">'+esc(t2)+
          '</span><span class="tcount">'+t2s[t2].length+'</span></div>';
        h += '<div class="cgrid'+(t2?' deep':'')+'">';
        for (const c of t2s[t2].slice(0, 300))
          h += '<span class="ccode">'+esc(c.code)+
            '<i class="cdel" title="Remove from the list" onclick="event.'+
            'stopPropagation();delCode('+
            JSON.stringify(c.code).replace(/"/g,'&quot;')+
            ')">&#10005;</i></span>';
        if (t2s[t2].length > 300)
          h += '<span class="muted" style="font-size:11px; padding:3px">+'+
            (t2s[t2].length-300)+' more — narrow with search</span>';
        h += '</div>';
      }
    }
    h += '</div>';
  }
  return h;
}

function toggleNode(p){
  OPEN[p] = !OPEN[p];
  refreshCodeTree();
}
function expandAll(on){
  OPEN = {};
  if (on) for (const c of (CODES && CODES.materials) || [])
    OPEN[c.product || '(uncategorised)'] = true;
  refreshCodeTree();
}

async function loadCodes(){
  const r = await api('/api/codes');
  if (r.error){ CODES = {error:r.error}; } else { CODES = r; }
  render();
}

function renderCodes(){
  if (!CODES){ loadCodes(); return '<div class="empty">Loading codes…</div>'; }
  if (CODES.error)
    return '<div class="empty">Code engine not available: '+
      esc(CODES.error)+'</div>';
  const list = CODES.materials || [];

  // Product / Cate1 totals
  const prods = {};
  for (const c of list){
    const p = c.product || '(uncategorised)';
    prods[p] = (prods[p] || 0) + 1;
  }
  const prodNames = Object.keys(prods).sort();

  const q = CODEQ.trim().toUpperCase();
  let shown = list;
  if (CODECAT) shown = shown.filter(
    c => (c.product || '(uncategorised)') === CODECAT);
  if (q) shown = shown.filter(c =>
    c.code.toUpperCase().includes(q) ||
    (c.product||'').toUpperCase().includes(q) ||
    (c.cate1||'').toUpperCase().includes(q) ||
    (c.cate2||'').toUpperCase().includes(q));

  let h = '<div class="kpirow">'+
    '<div class="kpi"><div class="val">'+list.length+'</div>'+
      '<div class="lbl">Material codes</div></div>'+
    '<div class="kpi"><div class="val" style="color:var(--accent)">'+
      prodNames.length+'</div><div class="lbl">Product groups</div></div>'+
    '</div>';

  // ── Upload ──
  h += '<div class="card setcard ov"><div class="cardhead">'+
    '<h3>Add codes from a price sheet'+faq('codes')+'</h3></div>'+
    '<div class="setbody">'+
    '<div class="frow"><label>File</label><div class="fctl">'+
    docPick('mm-file', 'Choose a price sheet')+
    '</div></div>'+
    '<div class="frow"><label>Code column</label><div class="fctl">'+
    '<input type="text" id="mm-col" class="short" placeholder="e.g. D" '+
      'style="width:110px">'+
    '</div></div>'+
    '<div class="frow"><label>Product / Type1</label><div class="fctl">'+
    '<div class="inline">'+
    '<input type="text" id="mm-pcol" class="short" placeholder="e.g. B" '+
      'style="width:110px">'+
    '<input type="text" id="mm-tcol" class="short" placeholder="e.g. C" '+
      'style="width:110px"></div>'+
    '</div></div>'+
    '<div class="setactions">'+
    exportSplit({id: 'codes', set: 'materials', label: 'Export codes',
      canFilter: shown.length > 0,
      filterHint: shown.length + ' of ' + list.length + ' codes',
      title: 'Download the code master as the upload file'})+
    '<button class="btn" onclick="exportMaterials()">Download CSV</button>'+
    '<button class="btn" onclick="clearMaterials()">Clear all codes</button>'+
    '<div class="spacer"></div>'+
    '<button class="btn primary" onclick="uploadMaterials()">'+
    'Upload &amp; Add</button></div></div></div>';

  // ── Code list ──
  // ── Tree: Product > Type 1 > Type 2 > code grid ──
  // The tree is its own function so the filter and the fold arrows can rebuild
  // just the body (refreshCodeTree) instead of re-rendering the page.
  h += '<div class="card"><div class="cardhead">'+
    '<h3>Material Code List</h3><span class="count" id="codecount">'+
    shown.length+' of '+list.length+'</span></div>'+
    '<div class="setbody" style="padding-bottom:10px"><div class="mrow">'+
    '<span class="chip'+(CODECAT?'':' role')+'" style="cursor:pointer" '+
    'onclick="CODECAT=\\'\\';render()">All ('+list.length+')</span>';
  for (const p of prodNames)
    h += '<span class="chip'+(CODECAT===p?' role':'')+'" '+
      'style="cursor:pointer" onclick="CODECAT='+
      JSON.stringify(p).replace(/"/g,'&quot;')+';render()">'+
      esc(p)+' ('+prods[p]+')</span>';
  h += '</div><div class="inline" style="margin-top:12px">'+
    '<input type="text" id="codeq" placeholder="Search code, product or type" '+
    'value="'+esc(CODEQ)+'" oninput="setCodeQ(this.value)" '+
    'style="max-width:280px">'+
    '<button class="btn" onclick="expandAll(true)">Expand all</button>'+
    '<button class="btn" onclick="expandAll(false)">Collapse all</button>'+
    '<span class="spacer" style="flex:1"></span>'+
    '<input type="text" id="c-code" placeholder="Add a code" '+
      'style="max-width:150px">'+
    '<input type="text" id="c-prod" placeholder="Product" '+
      'style="max-width:120px">'+
    '<input type="text" id="c-c1" placeholder="Type 1" '+
      'style="max-width:110px">'+
    '<input type="text" id="c-c2" placeholder="Type 2" '+
      'style="max-width:100px">'+
    '<button class="btn primary" onclick="addCode()">Add</button>'+
    '</div></div><div class="cardbody" style="padding:12px 16px 16px">'+
    '<div id="codetree">'+codesTreeHTML(shown)+'</div>';

  h += '</div></div>';

  // ── Unverified codes (found in POs) — bottom of the page ──
  const revs = CODES.reviews || [];
  if (revs.length){
    h += '<div class="card" style="border-color:#fcd34d">'+
      '<div class="cardhead"><h3>Unknown codes found in POs ('+revs.length+
      ')</h3><span class="count">Approve to add them</span>'+
      '<span class="spacer" style="flex:1"></span>'+
      '<button class="btn" onclick="clearUnknownCodes()" '+
      'title="Stop listing these. Nothing is added to the list and nothing is '+
      'approved - a cleared code still fails the gate on the next PO.">'+
      'Clear all</button></div>'+
      '<div class="cardbody"><table>'+
      '<tr><th>Code</th><th>Seen in PO</th><th>Context from the PO</th>'+
      '<th></th></tr>';
    for (const r of revs){
      h += '<tr class="warnrow"><td><b>'+esc(r.code)+'</b></td>'+
        '<td class="muted">'+esc(r.po_numbers.join(', '))+'</td>'+
        '<td class="ell" title="'+esc(r.context)+'">'+esc(r.context)+'</td>'+
        '<td><button class="btn primary" onclick="approveCode('+
        JSON.stringify(r.code).replace(/"/g,'&quot;')+')">Approve</button>'+
        '</td></tr>';
    }
    h += '</table></div></div>';
  }
  return h;
}

function uploadMaterials(){
  const f = document.getElementById('mm-file').files[0];
  if (!f){ alert('Choose a price sheet file first.'); return; }
  const fr = new FileReader();
  fr.onload = async () => {
    toast('Reading codes…');
    const r = await api('/api/mm_upload', {filename: f.name,
      data: fr.result.split(',')[1],
      code_col: document.getElementById('mm-col').value,
      product_col: document.getElementById('mm-pcol').value,
      type1_col: document.getElementById('mm-tcol').value});
    if (r.error){ alert(r.error); return; }
    const mapping = r.layout === 'mapping';
    let m = (mapping
        ? 'Product Mapping Table read from '+r.file
        : 'Found '+r.parsed+' code(s) in '+r.file)+
      '\\n\\nNew codes added: '+r.added+
      '\\nAlready in the list: '+(r.parsed - r.added)+
      '\\nTotal now: '+r.total+
      '\\n\\nCode column: '+(r.code_column||'?')+
      '\\nCategory columns: '+(r.category_columns||'?');
    if (r.group_count)
      m += '\\n\\nGroups detected ('+r.group_count+'): '+
        (r.groups||[]).join(', ');
    if (mapping){
      m += '\\n\\nShort SKU → FULL SKU mappings loaded: '+r.sku_mapped+
        '\\nA PO that prints a short SKU is rewritten to its FULL SKU.';
      if (r.sku_picked){
        m += '\\n\\n'+r.sku_picked+' short SKU(s) map to more than one FULL '+
          'SKU. One was chosen for each: /AA when it is offered, never '+
          'anything ending /AC, otherwise a fixed pick per short SKU (so the '+
          'same PO always gives the same code). The alternatives are kept on '+
          'each mapping row if you want a different one.';
      }
      if (r.sku_ambiguous){
        m += '\\n\\n⚠️ '+r.sku_ambiguous+' short SKU(s) list ONLY /AC FULL '+
          'SKUs. That variant is not sold on this flow, so those are left '+
          'exactly as printed and land in the unknown list for a human.';
      }
    }
    if (r.sample && r.sample.length)
      m += '\\n\\nFirst rows:\\n' + r.sample.map(x =>
        '  '+x.code+'  |  '+[x.product,x.cate1,x.cate2]
          .filter(Boolean).join(' / ')).join('\\n');
    alert(m);
    await loadCodes();
  };
  fr.readAsDataURL(f);
}

async function clearMaterials(){
  if (!confirm('Remove every Material Code from the list?\\n\\n'+
    'Use this when the Product / Type grouping is wrong. '+
    'Upload your price sheet again afterwards to rebuild it.')) return;
  toast('Clearing…');
  const r = await api('/api/mm_clear', {});
  if (r.error){ alert(r.error); return; }
  alert('Removed '+r.removed+' code(s). Upload your price sheet again.');
  await loadCodes();
}

async function exportMaterials(){
  toast('Exporting…');
  const r = await api('/api/mm_export', {});
  if (r.error) alert(r.error);
}

async function delCode(code){
  if (!confirm('Remove '+code+' from the Material Code list?')) return;
  await api('/api/mm_delete', {code: code});
  await loadCodes();
}

async function approveCode(code){
  const r = await api('/api/mm_add', {code: code});
  if (r.error){ alert(r.error); return; }
  toast(r.message || 'Added');
  await loadCodes();
}

// "Unknown codes found in POs" -> Clear all.
//
// This clears the LIST, not the data: nothing is added to the Material Code
// list, and a cleared code still fails the gate on the next PO (it will show up
// on the review card again, unticked). The extraction cache is untouched, so
// the evidence of what each PO said survives.
async function clearUnknownCodes(){
  const revs = (CODES.reviews || []);
  if (!revs.length) return;
  if (!confirm('Clear all '+revs.length+' unknown code(s) from this list?\\n\\n'+
      'Nothing is approved and nothing is added to the Material Code list. '+
      'A cleared code still fails the gate on the next PO - this only stops '+
      'it being listed here.\\n\\n'+
      'Use Approve on a row instead if the code is real.')) return;
  toast('Clearing…');
  const r = await api('/api/mm_clear_reviews', {});
  if (r.error){ alert(r.error); return; }
  await loadCodes();
  toast((r.cleared || 0)+' code(s) cleared from the list');
}

async function addCode(){
  const r = await api('/api/mm_add', {
    code: document.getElementById('c-code').value,
    product: document.getElementById('c-prod').value,
    cate1: document.getElementById('c-c1').value,
    cate2: document.getElementById('c-c2').value});
  alert(r.message || r.error);
  if (r.ok) await loadCodes();
}


let SET_SMODE = null;   // radio selection state before saving

function pickSMode(v){ SET_SMODE = v; render(); }

// Settings is now one card per concern, stacked:
//
//   DeepSeek API  endpoint · key · model      (what reads a PO)
//   Email box  mailbox · folder · rules      (what gets collected)
//
// They are separate because they fail separately and are looked after by
// different people. Both still post to /api/settings in one request, so a
// single Save cannot leave the two halves disagreeing.
function renderSettings(){
  const s = DATA.settings || {};
  const o = s.outlook || {};
  // The PO-reading endpoint as the server actually resolved it (settings >
  // environment > claude_config.json). Shown as the box's placeholder so an
  // empty box still tells you where a PO will go.
  const CL = s.deepseek || {};
  return '<div class="setstack">'+ apiSettingsCard(CL) +
    emailSettingsCard(s, o) +
    syncSettingsCard()+ storageCard()+
    '<div class="card setcard" style="border-color:#fecaca">'+
    '<div class="cardhead"><h3>Reset for Re-testing'+faq('setreset')+'</h3></div>'+
    '<div class="setbody">'+
    '<button class="btn danger" onclick="resetProcessing()">'+
    'Reset All Processing</button></div></div>'+
    '</div>';
}

// ── Settings · API ───────────────────────────────────────────────────────
function apiSettingsCard(CL){
  // This card quotes the endpoint it resolved, so its explanation is built here
  // instead of being written once in the FAQ table above.
  FAQ.setapi = apiFaqText(CL);
  // The model list comes from the guide (claude_engine.KNOWN_MODELS), so the
  // dropdown cannot offer an ID this endpoint does not serve - a wrong one is
  // a bare HTTP 400 with no reading behind it.
  let modelOpts = '<option value=""'+((CL.stored_model) ? '' : ' selected')+
    '>Default — '+(esc(CL.default_model || CL.model) || 'the built-in one')+
    '</option>';
  (CL.models || []).forEach(m => {
    modelOpts += '<option value="'+esc(m.id)+'"'+
      ((CL.stored_model === m.id) ? ' selected' : '')+'>'+
      esc(m.id)+' — '+esc(m.note || '')+'</option>';
  });
  return '<div class="card setcard">'+
    '<div class="cardhead"><h3>'+esc(CL.provider || 'API')+faq('setapi')+'</h3>'+
    '<span class="count">'+(CL.model ? 'reading with '+esc(CL.model) : '')+
    '</span></div>'+
    '<div class="setbody">'+
    '<div class="subfields">'+
      '<div class="frow"><label>Endpoint</label>'+
        '<div class="fctl">'+
        '<input type="text" id="set-poendpoint" autocomplete="off" '+
          'placeholder="'+(esc(CL.base_url || 'the address from '+
            'claude_config.json'))+'" '+
          'value="'+esc(CL.stored_base_url || '')+'">'+
        '</div></div>'+
      '<div class="frow"><label>Model</label>'+
        '<div class="fctl">'+
        '<select id="set-clmodel">'+modelOpts+'</select>'+
        '</div></div>'+
      '<div class="frow"><label>API key</label>'+
        '<div class="fctl">'+
        '<input type="password" id="set-claudekey" autocomplete="off" '+
          'placeholder="'+((CL.key_set) ?
            'a key is stored — paste a new one to replace it' :
            'paste the DeepSeek API key here (required)')+'">'+
        '</div></div>'+
    '</div>'+
    '<div class="setactions">'+
      '<button class="btn" onclick="testPoReading()">Test PO reading</button>'+
      '<span class="spacer" style="flex:1"></span>'+
      '<button class="btn primary" onclick="saveSettings(false)">Save</button>'+
    '</div><div id="ptest"></div></div></div>';
}

// ── Settings · Email box ────────────────────────────────────────────────
function emailSettingsCard(s, o){
  return '<div class="card setcard">'+
    '<div class="cardhead"><h3>Email box'+faq('setmail')+'</h3></div>'+
    '<div class="setbody">'+
    '<div class="subfields">'+
      '<div class="frow"><label>Mailbox</label>'+
        '<div class="fctl">'+
        '<div class="inline">'+
        '<select id="set-mailbox-sel" onchange="pickMailbox(this.value)">'+
          mailboxOptions(o.mailbox_name||'')+'</select>'+
        '<button class="btn" onclick="loadMailboxes()">Refresh</button>'+
        '</div>'+
        '<input type="text" id="set-mailbox" value="'+
          esc(o.mailbox_name||'')+'" '+
          'placeholder="or type a name — blank = my default inbox">'+
        '</div></div>'+
      '<div class="frow"><label>Lookback</label>'+
        '<div class="fctl"><div class="inline">'+
        '<input type="number" id="set-lookback" min="1" class="short" '+
          'value="'+esc(o.lookback_days||1)+'"><span class="muted">days'+
          '</span></div></div></div>'+
      '<div class="frow"><label>Filter</label>'+
        '<div class="fctl"><label class="inline" style="cursor:pointer">'+
        '<input type="checkbox" id="set-attonly" style="width:auto"'+
          (o.attachments_only ? ' checked' : '')+'>'+
        '<span>Only emails with a document attachment (PDF, Excel…)</span>'+
        '</label>'+
        '</div></div>'+
      '<div class="frow"><label>PO number</label>'+
        '<div class="fctl">'+
        '<select id="set-poregex">'+
          (DATA.po_presets||[]).map(p =>
            '<option value="'+esc(p.value)+'"'+
            ((DATA.po_regex||'') === p.value ? ' selected' : '')+'>'+
            esc(p.label)+'</option>').join('')+
        '</select>'+
        '</div></div>'+
      '<div class="frow"><label>DRM files</label>'+
        '<div class="fctl"><label class="inline" style="cursor:pointer">'+
        '<input type="checkbox" id="set-pdfdel" style="width:auto"'+
          ((DATA.pdf_delegation === false) ? '' : ' checked')+'>'+
        '<span>Ask Acrobat / Word to open DRM-protected PO files</span>'+
        '</label>'+
        '</div></div>'+
    '</div>'+

    '<div class="setactions">'+
      '<button class="btn" onclick="testOutlook()">Test connection</button>'+
      '<span class="spacer" style="flex:1"></span>'+
      '<button class="btn" onclick="saveSettings(false)">Save</button>'+
      '<button class="btn primary" onclick="saveSettings(true)">'+
        'Save &amp; Collect Now</button>'+
    '</div><div id="otest"></div></div></div>';
}

async function resetProcessing(){
  if (!confirm('Reset all processing decisions?\\n'+
      'Emails and Customer Master will be kept.')) return;
  const r = await api('/api/reset_processing', {});
  alert(r.message || r.error);
  await load();
}

let MAILBOXES = null;   // mailbox list of the Outlook profile (filled on test)

function mailboxOptions(cur){
  let h = '<option value=""'+(cur?'':' selected')+
    '>(my default inbox)</option>';
  const list = MAILBOXES || (cur ? [cur] : []);
  for (const m of list)
    h += '<option'+(m===cur?' selected':'')+'>'+esc(m)+'</option>';
  if (!MAILBOXES)
    h += '<option value="__load__">Load mailbox list…</option>';
  return h;
}

// `cur` is passed explicitly when the caller is not the Settings screen: that
// form's #set-mailbox does not exist on the Inbox, and reading it there threw.
async function loadMailboxes(cur){
  toast('Reading Outlook mailboxes…');
  const box = document.getElementById('set-mailbox');
  const r = await api('/api/outlook_test', {mailbox_name:
    cur !== undefined ? cur : (box ? box.value : '')});
  if (r.mailboxes && r.mailboxes.length){
    MAILBOXES = r.mailboxes;
    render();
    toast(r.mailboxes.length + ' mailbox(es) found');
  } else {
    alert(r.error || 'No mailboxes found. Open Outlook and sign in first.');
  }
}

function pickMailbox(v){
  if (v === '__load__'){ loadMailboxes(); return; }
  document.getElementById('set-mailbox').value = v;
}

// ── Collecting, from either screen ───────────────────────────────────────
// ONE implementation, because the two entry points drifted: Settings > "Save &
// Collect Now" collected and then only moved the date WHEN the server reported
// one, leaving the user on the Settings form looking at an unchanged Inbox -
// which reads as "the mailbox change did nothing". It now always lands on the
// Inbox at the newest collected date, and says plainly when nothing was found.
// ── Long jobs, with a real activity indicator ─────────────────────────────
// Reading a mailbox goes through Outlook over COM, one item at a time, and can
// take a minute. Waiting on the POST is what made "switch mailbox" feel dead:
// the request was in flight, nothing on screen moved, and the only feedback was
// a toast that said Collecting… and stayed there.
//
// Now the request is fired without being awaited, /api/sync_state is polled for
// done/total, and the overlay draws a RING when that ratio is real and three
// bouncing dots when it is not. No invented percentage: SYNC.total stays 0 when
// Outlook will not report a count, and that is exactly when the dots show.
const RING_C = 2 * Math.PI * 22;   // r=22 inside the 54px box

function sleep(ms){ return new Promise(r => setTimeout(r, ms)); }

function busyOpen(title, sub){
  let el = document.getElementById('busy');
  if (!el){
    el = document.createElement('div');
    el.id = 'busy';
    document.body.appendChild(el);
  }
  el.innerHTML = '<div class="busybox">'+
    '<div class="ringwrap" id="busyring"></div>'+
    '<div><div class="busytitle">'+esc(title)+'</div>'+
    '<div class="busysub" id="busysub">'+esc(sub || '')+'</div></div>'+
    '</div>';
  el.classList.add('open');
  busyState({});
}

// Swap between the ring and the dots, never both, and only redraw when the mode
// actually changes - rebuilding the SVG every poll would restart its animation.
function busyState(st){
  const wrap = document.getElementById('busyring');
  if (!wrap) return;
  st = st || {};
  const total = Number(st.total || 0);
  const done = Number(st.done || 0);
  const pct = total > 0 ? Math.max(0, Math.min(100,
    Math.round(done * 100 / total))) : null;
  if (pct === null){
    if (wrap.dataset.mode !== 'dots'){
      wrap.dataset.mode = 'dots';
      wrap.innerHTML = '<div class="fdots"><b></b><b></b><b></b></div>';
    }
  } else {
    if (wrap.dataset.mode !== 'ring'){
      wrap.dataset.mode = 'ring';
      wrap.innerHTML = '<svg class="ring" viewBox="0 0 54 54">'+
        '<circle class="bg" cx="27" cy="27" r="22"></circle>'+
        '<circle class="fg" cx="27" cy="27" r="22" '+
          'stroke-dasharray="'+RING_C.toFixed(1)+'" '+
          'stroke-dashoffset="'+RING_C.toFixed(1)+'"></circle>'+
        '</svg><span class="pct" id="busypct"></span>';
    }
    const fg = wrap.querySelector('.fg');
    if (fg) fg.style.strokeDashoffset = (RING_C * (1 - pct / 100)).toFixed(1);
    const p = document.getElementById('busypct');
    if (p) p.textContent = pct + '%';
  }
  const sub = document.getElementById('busysub');
  if (sub && st.phase) sub.textContent = st.phase;
}

function busyClose(){
  const el = document.getElementById('busy');
  if (el) el.classList.remove('open');
}

// Run `job` (which returns a promise) under the overlay, polling the server's
// collection state until it is no longer running.
async function runWithProgress(job, title, sub){
  busyOpen(title, sub);
  let out = null;
  let done = false;
  job().then(r => { out = r; done = true; })
       .catch(e => { out = {error: String(e)}; done = true; });
  let sawRunning = false;
  for (let i = 0; i < 1800; i++){          // 10 minutes at 350ms
    await sleep(350);
    let st = null;
    try { st = await api('/api/sync_state'); } catch (_) { st = null; }
    if (st){
      if (st.running) sawRunning = true;
      busyState(st);
      if (sawRunning && !st.running) break;   // it finished
      if (!sawRunning && st.error) break;     // it never started
    }
    // The request itself came back: one more look at the state, then stop.
    if (done && (!st || !st.running)) break;
  }
  busyClose();
  return out;
}

async function runCollect(opts){
  opts = opts || {};
  const r = await runWithProgress(
    () => api('/api/collect', opts.body || {}),
    opts.title || 'Collecting email from Outlook',
    opts.sub || 'Connecting to Outlook…');
  if (!r) return null;
  if (r.error){ alert(r.error); return null; }
  if (r.latest_date) SELDATE = r.latest_date;
  const dp = document.getElementById('datepick');
  if (dp) dp.value = SELDATE;
  TAB = 'today';
  MAILPAGE = 0;
  await load();
  return r;
}

// Called by Settings > "Save & Collect Now", after the settings POST.
async function collectFromSettings(){
  const r = await runCollect({title: 'Collecting email from Outlook',
                              sub: 'Connecting to Outlook…'});
  if (r) alert(r.message || 'Collected.');
}

// The Inbox's own mailbox picker. The mailbox is saved and read in ONE request:
// as two, the page rendered once against the old mailbox (a full re-render of
// the table) before the collect had even started, which is most of what made
// switching feel slow.
//
// No modal on success - switching mailboxes is routine, and a dialog per switch
// trains people to dismiss dialogs. The count goes to a toast; a failure still
// gets an alert.
async function inboxMailbox(v){
  if (v === '__load__'){ loadMailboxes(''); return; }
  const r = await runCollect({body: {mailbox: v},
                              title: 'Switching mailbox',
                              sub: v || 'Connecting to Outlook…'});
  if (!r) return;
  if (r.mailbox && DATA && DATA.settings){
    DATA.settings.outlook = DATA.settings.outlook || {};
    DATA.settings.outlook.mailbox_name = r.mailbox;
  }
  toast((r.message || 'Collected.').split('\\n')[0]);
}

// File the mail that was collected before the mailbox was recorded. Outlook is
// touched only to learn the store's ID, so this is a blink rather than the
// minute a collection takes - which is why it is a link on the notice and not
// "press Sync this date and hope".
async function claimMailbox(){
  toast('Filing older email…', true);
  const r = await api('/api/claim_mailbox', {});
  hideToast();
  if (r.error){ alert(r.error); return; }
  toast(r.message || 'Done.');
  await load();
}

async function testOutlook(){
  const box = document.getElementById('otest');
  box.innerHTML = '<div class="otest">Testing…</div>';
  const r = await api('/api/outlook_test',
    {mailbox_name: document.getElementById('set-mailbox').value});
  if (r.mailboxes && r.mailboxes.length) MAILBOXES = r.mailboxes;
  if (r.error && !r.mailboxes){
    box.innerHTML = '<div class="otest bad"><b>Failed</b><br>'+
      esc(r.error)+'</div>';
    return;
  }
  let h = '<div class="otest '+(r.ok?'good':'bad')+'">';
  h += '<b>'+(r.ok ? '&#10003; Connected' : '&#10005; Not connected')+
    '</b><table class="otbl">';
  const row = (k,v) => v ? '<tr><td>'+k+'</td><td>'+esc(v)+'</td></tr>' : '';
  h += row('Outlook version', r.outlook);
  h += row('Signed in as', r.profile);
  h += row('Mailboxes found', (r.mailboxes||[]).join('  |  '));
  h += row('Target mailbox', r.target);
  h += row('Folder', r.folder);
  if (r.count !== null && r.count !== undefined)
    h += row('Emails in folder', String(r.count));
  h += row('Newest email', r.latest);
  if (r.error) h += row('Error', r.error);
  if (r.hint)  h += row('What to do', r.hint);
  h += '</table></div>';
  box.innerHTML = h;
}

function storageCard(){
  const d = DATA.disk || {};
  const days = ((DATA.settings||{}).retention || {}).attachments_days;
  return '<div class="card setcard">'+
    '<div class="cardhead"><h3>Storage &amp; Cleanup'+faq('setstorage')+'</h3>'+
    '<span class="count">'+(d.size_mb||0)+' MB attachments &middot; '+
    (d.db_mb||0)+' MB database</span></div>'+
    '<div class="setbody">'+
    '<div class="frow"><label>Keep for</label><div class="fctl">'+
    '<div class="inline"><input type="number" id="ret-days" min="0" '+
    'step="30" class="short" value="'+esc(days===undefined?180:days)+'">'+
    '<span class="muted">days</span></div></div></div>'+
    '<div class="setactions">'+
    '<button class="btn" onclick="runCleanup(true)">Preview</button>'+
    '<div class="spacer"></div>'+
    '<button class="btn primary" onclick="runCleanup(false)">'+
    'Save &amp; Clean up now</button></div>'+
    '<div id="cleanres"></div></div></div>';
}

async function runCleanup(dry){
  const r = await api('/api/cleanup', {dry_run:dry,
    attachments_days: document.getElementById('ret-days').value});
  const box = document.getElementById('cleanres');
  if (r.error){ box.innerHTML = '<div class="otest bad">'+esc(r.error)+
    '</div>'; return; }
  if (!r.enabled){
    box.innerHTML = '<div class="otest">Cleanup is off (0 days) — '+
      'attachments are kept forever.</div>';
    return;
  }
  box.innerHTML = '<div class="otest good">'+
    (dry ? '<b>Preview</b> — ' : '<b>Done</b> — ')+
    r.deleted+' file(s), '+r.freed_mb+' MB '+
    (dry ? 'would be removed' : 'removed')+
    ' (received before '+esc(r.cutoff)+').</div>';
  if (!dry) await load();
}

function syncSettingsCard(){
  const c = (DATA.settings || {}).sync || {};
  const mode = SET_SMODE || c.mode || 'interval';
  const times = (c.times || ['09:00','14:00']);
  return '<div class="card setcard">'+
    '<div class="cardhead"><h3>Automatic Sync'+faq('setsync')+'</h3></div>'+
    '<div class="setbody">'+
    '<label class="opt'+(mode==='interval'?' on':'')+'">'+
      '<input type="radio" name="smode" value="interval" '+
      (mode==='interval'?'checked':'')+' onchange="pickSMode(\\'interval\\')">'+
      '<span><b>Every N minutes</b></span></label>'+
    '<div class="subfields'+(mode==='interval'?'':' off')+'">'+
      '<div class="frow"><label>Interval</label><div class="fctl">'+
      '<div class="inline"><input type="number" id="s-int" min="5" step="5" '+
      'class="short" value="'+esc(c.interval_min||60)+'">'+
      '<span class="muted">minutes</span></div></div></div></div>'+

    '<label class="opt'+(mode==='times'?' on':'')+'">'+
      '<input type="radio" name="smode" value="times" '+
      (mode==='times'?'checked':'')+' onchange="pickSMode(\\'times\\')">'+
      '<span><b>At fixed times</b></span></label>'+
    '<div class="subfields'+(mode==='times'?'':' off')+'">'+
      '<div class="frow"><label>Run at</label><div class="fctl">'+
      '<div class="inline">'+
      '<input type="time" id="s-t1" class="short" style="width:120px" '+
      'value="'+esc(times[0]||'09:00')+'">'+
      '<input type="time" id="s-t2" class="short" style="width:120px" '+
      'value="'+esc(times[1]||'')+'"></div>'+
      '</div></div></div>'+

    '<label class="opt'+(mode==='off'?' on':'')+'">'+
      '<input type="radio" name="smode" value="off" '+
      (mode==='off'?'checked':'')+' onchange="pickSMode(\\'off\\')">'+
      '<span><b>Off</b></span></label>'+

    '<div class="setactions"><div class="spacer"></div>'+
    '<button class="btn primary" onclick="saveSync()">Save schedule</button>'+
    '</div></div></div>';
}

async function saveSync(){
  const mode = document.querySelector('input[name=smode]:checked').value;
  const t1 = document.getElementById('s-t1').value;
  const t2 = document.getElementById('s-t2').value;
  const r = await api('/api/sync_config', {mode:mode,
    interval_min: document.getElementById('s-int').value,
    times: [t1, t2].filter(Boolean)});
  if (r.error){ alert(r.error); return; }
  toast('Schedule saved');
  await load();
}

// Settings > "Test PO reading". Three states, rendered in the same block and
// with the same classes as the Outlook test beside it:
//   waiting  the request is in flight          -> .otest
//   success  endpoint + model + latency + reply -> .otest.good + .otbl
//   failure  the message AND what to do about it -> .otest.bad
async function testPoReading(){
  const box = document.getElementById('ptest');
  const urlBox = document.getElementById('set-poendpoint');
  const keyBox = document.getElementById('set-claudekey');
  // Test what is typed in, not only what was saved: typing a key and pressing
  // Test is the obvious order of actions, and failing that would be a lie.
  box.innerHTML = '<div class="otest">Contacting the endpoint…</div>';
  const r = await api('/api/po_test', {
    base_url: (urlBox||{}).value || '',
    api_key: (keyBox||{}).value || '',
  });
  if (r.error && !r.endpoint){
    box.innerHTML = '<div class="otest bad"><b>Failed</b><br>'+
      esc(r.error)+(r.hint ? '<br><i>'+esc(r.hint)+'</i>' : '')+'</div>';
    return;
  }
  let h = '<div class="otest '+(r.ok?'good':'bad')+'">';
  h += '<b>'+(r.ok ? '&#10003; The endpoint answered' :
    '&#10005; The endpoint did not answer')+'</b><table class="otbl">';
  const row = (k,v) => v ? '<tr><td>'+k+'</td><td>'+esc(v)+'</td></tr>' : '';
  h += row('Endpoint', r.endpoint);
  h += row('Model', r.model);
  h += row('Round trip', r.latency_ms ? r.latency_ms+' ms' : '');
  h += row('Reply', r.reply);
  if (r.error) h += row('Error', r.error);
  if (r.hint)  h += row('What to do', r.hint);
  h += '</table></div>';
  box.innerHTML = h;
}

async function saveSettings(collectNow){
  // Both cards save through this one request, so the API half and the mailbox
  // half can never be written from two different snapshots of the form. Each
  // field is guarded: a card that is not on screen contributes nothing rather
  // than throwing and losing the other card's changes.
  const el = id => document.getElementById(id);
  const val = id => { const e = el(id); return e ? e.value : undefined; };
  const body = {};
  if (val('set-mailbox') !== undefined) body.mailbox_name = val('set-mailbox');
  if (val('set-lookback') !== undefined)
    body.lookback_days = val('set-lookback');
  if (el('set-attonly')) body.attachments_only = el('set-attonly').checked;
  if (el('set-pdfdel')) body.pdf_delegation = el('set-pdfdel').checked;
  const ck = el('set-claudekey');
  // Blank = "keep the stored token", so saving the rest of the form never
  // wipes it by accident.
  if (ck && ck.value) body.deepseek_api_key = ck.value;
  const ep = el('set-poendpoint');
  // Blank here means "use the address in claude_config.json", which is a real
  // choice, so the empty value is sent rather than skipped.
  if (ep) body.deepseek_base_url = ep.value;
  const md = el('set-clmodel');
  // Blank means "back to the built-in default", so it is sent as "".
  if (md) body.deepseek_model = md.value;
  if (val('set-poregex') !== undefined) body.po_regex = val('set-poregex');
  const r = await api('/api/settings', body);
  if (r.error){ alert(r.error); return; }
  if (collectNow){
    // Shared with the Inbox's mailbox picker - see runCollect(). It sets the
    // date, switches to the Inbox and reloads; the old inline copy only did
    // that when the server happened to report a date, which is why saving a
    // mailbox could leave the Inbox looking untouched.
    await collectFromSettings();
    return;
  }
  await load();
}

function render(){
  updateBadges();
  // The account popup is anchored to a cell that is about to be destroyed;
  // leaving it up would leave a list floating over the new screen.
  pcClose();
  renderSyncBox();
  document.querySelectorAll('.navbtn').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === TAB));
  let title = TITLES[TAB];
  if (TAB === 'today')
    title = SELDATE === localToday()
      ? "Inbox" : "Inbox — " + fmtDate(SELDATE);
  document.getElementById('title').textContent = title;
  // One marker in the head, whatever the screen: the prose that used to sit in
  // a .cardnote under the first card now hangs off the title it belongs to.
  const tf = document.getElementById('titlefaq');
  if (tf){
    const fk = screenFaq();
    tf.innerHTML = fk ? faq(fk) : '';
  }
  renderApiWarn();
  const fns = {today:renderToday,
    notmypo:renderNotMyPO, completed:renderCompleted, history:renderDashboard,
    master:renderMaster,
    codes:renderCodes, settings:renderSettings, quick:renderQuick};
  document.getElementById('content').innerHTML = fns[TAB]();
  // Turn the buttons' native `title` into the sliding tooltip. After the innerHTML
  // swap, because the buttons are new elements every render.
  initBtnTips();
  if (TAB === 'quick') wireDrop();
  // The Ship-To grid is paged, so its body is fetched rather than rendered from
  // DATA: fill it once the placeholder is in the document.
  if (TAB === 'master'){ loadShip(); loadDom(); }
}

document.querySelectorAll('.navbtn').forEach(b =>
  b.addEventListener('click', () => {
    TAB = b.dataset.tab;
    CUSTOPEN = false;        // the tick panel belongs to the Inbox
    toggleSidebar(false);    // the plate covers the page it just opened
    render();
  }));

// "Reset all settings" - the last row of the menu's footer.
//
// Says exactly what goes and what stays BEFORE doing it, because "reset all
// settings" could plausibly mean "also clear my Master Data" and that is a day
// of re-uploading. The token is part of it: a reset that kept a credential
// would not be a reset.
async function resetAllSettings(){
  if (!confirm('Reset all settings to their defaults?\\n\\n'+
      'CLEARED: API endpoint, API key, model choice, mailbox / folder, '+
      'lookback, PO-number rule, output format, sync schedule, retention, '+
      'PDF delegation.\\n\\n'+
      'KEPT: Master Data (customers, Ship-To, material codes, product '+
      'mapping), collected emails, attachments and generated files.\\n\\n'+
      'You will have to paste the DeepSeek API key again before any PO can be '+
      'read.')) return;
  toast('Resetting…');
  const r = await api('/api/settings_reset', {});
  if (r.error){ alert(r.error); return; }
  await load();
  alert('Settings reset.\\n\\nCleared: '+
    ((r.reset||[]).join(', ') || '(nothing was set)')+
    '\\n\\nPaste the DeepSeek API key on Settings > API before reading a PO.');
}

// ── "PO reading is not connected" ──────────────────────────────────────────
// Shown in the top corner of the Inbox and of Quick Convert - the two screens
// that read a PO. The state comes from the SERVER (settings.deepseek.key_set),
// which resolves the token exactly as the reader does (Settings > environment
// > .api_key), so the badge cannot disagree with whether a PO would be read.
//
// It exists because of the failure this project keeps having to explain: with
// no token, every PO comes back with ZERO material codes and NOTHING fails.
// That is indistinguishable from a parsing bug, and it cost a round trip here.
function renderApiWarn(){
  const el = document.getElementById('apiwarn');
  if (!el) return;
  const CL = ((DATA && DATA.settings) || {}).deepseek || {};
  if ((TAB !== 'today' && TAB !== 'quick') || CL.key_set){
    el.innerHTML = '';
    return;
  }
  const why = CL.error
    ? CL.error
    : 'No DeepSeek API key is stored, so no document can be read.';
  el.innerHTML =
    '<span class="apiwarn" tabindex="0" role="button" '+
      'onclick="openApiSettings()" '+
      'title="API not connected - click to open Settings">'+
      '<span class="aw-ico">!</span> API not connected'+
      '<span class="aw-tip">'+
        '<b>PO reading is not connected</b>'+
        '<span class="aw-why">'+esc(why)+'</span>'+
        '<span class="aw-how">A PO would come back with <b>zero material '+
          'codes</b> and no error at all, which looks like a parsing bug '+
          'rather than a setup one.</span>'+
        '<span class="aw-how" style="margin-top:7px">Paste the DeepSeek '+
          'API key on <b>Settings &rarr; API</b> and press <b>Test PO '+
          'reading</b>. The endpoint itself is already configured.</span>'+
        '<span class="aw-link">Open Settings &rarr;</span>'+
      '</span>'+
    '</span>';
}

function openApiSettings(){ TAB = 'settings'; render(); }

// ── The "?" markers ───────────────────────────────────────────────────────
// Every screen used to open with a paragraph explaining itself, and every field
// in Settings carried a grey line underneath. Each was worth reading once and
// then cost a row on every later visit. So the prose lives here instead, behind
// a marker in the corner of the very thing it explains: same words, none of the
// height.
//
// One marker per CONTAINER, not per sentence. A card that had a paragraph plus
// four field hints gets one marker holding all five lines, because four
// markers down the side of one card is the clutter it was meant to remove.
//
// The bubble is the SAME element the buttons use (see the tooltip section
// below) switched to a rich layout - a second tooltip implementation would
// drift from the first the moment either got touched.
const FAQ_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '+
  'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '+
  'aria-hidden="true"><circle cx="12" cy="12" r="10"/>'+
  '<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/></svg>';

const FAQ = {
  // ── Inbox and its three lists ──
  // The three tabs are the pipeline now: Extract sends the row to <b>Read</b>,
  // where the document is read and the file format is chosen, and Generate lands
  // in <b>Output</b>. Each tab's marker says what that step is.
  inbox: '<b>Extract</b> reads the PO and opens it in <b>Read</b> - that is '+
    'where the reading is checked and the file (<b>Full</b>, <b>Simple</b>, or '+
    'both) is chosen. <b>Generate</b> then writes it and opens <b>Output</b>.',
  discarded: 'Discarded emails are left out of every PO count and report. '+
    'A wrong call can be undone with <b>Rescue</b>.',
  read: 'A reading is kept on disk the moment a PO is read, so this list is '+
    'the extraction cache - opening it buys nothing from the API. Open a row '+
    'for the delivery address, the RDD and the lines that were read; '+
    '<b>Full</b> / <b>Simple</b> at its right end writes the file from that '+
    'cached reading, not from a new one. An <b>Extract</b> from the Inbox '+
    'opens here too: first the reading, then what it produced.',
  output: 'Confirmed POs for the day, oldest first. Download the Order '+
    'Upload file, key it into ERP, then <b>Mark uploaded</b>. <b>Undo</b> '+
    'puts one back for reprocessing.',
  // ── Dashboard ──
  trend: 'A PO counts on the day it was <b>confirmed</b>, not the day the '+
    'mail arrived. Each card compares the same length of time: this week so '+
    'far against the same days last week, this month against the same day '+
    'last month. <b>New</b> means the earlier period had nothing to compare '+
    'against.',
  // ── Quick Convert ──
  quickfolder: 'Point OrderFlow at the folder where the PO files are - paste '+
    'a path and press Enter, or use Browse. Files are read in place, never '+
    'copied. This is also the only way to process DRM-protected POs: a '+
    'browser upload always arrives encrypted, because the browser is not an '+
    'authorised process.',
  quickdrop: 'Convert extracts three things only - Material Code, '+
    'quantity and unit cost. The PO number is read from the file when it is '+
    'there.',
  quickresult: 'Edit any cell before downloading. Only ticked lines are '+
    'written: <b>Full</b> takes Material Code, Quantity and Unit Cost plus '+
    'the PO number when it is known; <b>Simple</b> writes PO #, Material '+
    'Code, Sales Quantity and Unit Price into those four columns. Both can be '+
    'ticked at once - the review is written out twice, one file each.',
  rdd: 'R.D.D is a <b>default</b>: the PO printed no required-delivery date, '+
    'so the date falls back to the one shown here. Type one above if the '+
    'customer asked for a specific day.',
  flowread: 'The delivery address, the PO date and the required delivery date '+
    'are read out of the document - a scanned or DRM-protected PO can take up '+
    'to a minute. Nothing is written and no row changes yet: the page that '+
    'follows shows what will land in each column and is where the output file '+
    'is chosen. That is also why Generate reuses this one reading instead of '+
    'buying a second.',
  pvfixed: 'Sales Org, Division and the EDI1 currency are fixed and not '+
    'shown. Material Code, Quantity and Unit Price ARE read, but they are '+
    'reviewed line by line on Quick Convert rather than listed here.',
  // ── Customer Master ──
  master: 'The customer data is <b>two tables</b>: the <b>Ship-To '+
    'locations</b> (one row per Sold-To / Ship-To pair, which fills ERP '+
    'columns N, R, W, X, AI and D) and the <b>Domains</b> table, whose DOMAIN '+
    'is the identity every mail is matched by. They join on the customer '+
    'name, so either can be edited on its own. A cell saves when you leave '+
    'the box.',
  mastership: 'One row per (Sold-To, Ship-To) pair. The table is '+
    '<b>rebuilt</b> from the file - rows it does not contain are dropped, so '+
    'never upload the blank template. The domains live in their own table '+
    'below.',
  masterdom: 'Two columns: the customer name and its DOMAIN. The table is '+
    '<b>rebuilt</b> from the file. Uploading it leaves the Ship-To table '+
    'untouched, and the other way round.',
  // ── Material Codes ──
  codes: 'Upload any customer price sheet: only the model codes are kept - '+
    'prices and customer names are not stored. Section rows such as '+
    '&quot;REFRIGERATION - FRENCH DOOR - 3DR&quot; become Product / Type 1 / '+
    'Type 2, and a code already in the list is skipped, so the same file can '+
    'be uploaded twice safely.<br>A <b>Product Mapping Table</b> is '+
    'recognised by its own header - it needs <b>FULL SKU</b> and <b>short '+
    'skus</b> - and loads the short-SKU &rarr; FULL-SKU rewrite, grouping by '+
    '<b>MATERIAL GROUP</b> instead.<br>The code / Product / Type boxes are '+
    'for the price-sheet layout: the code column is detected from the header, '+
    'so leave them blank unless auto-detect picks the wrong column.',
  // ── Settings ──
  setreset: 'Clears all the processing you have done - Confirm / Reject, ERP '+
    'upload checks and Discarded decisions - so every email returns to its '+
    'just-collected state. Collected emails, Customer Master and your '+
    'machine setup (PO-reading endpoint and token, port) are NOT deleted: '+
    'this is the re-testing button, not a factory reset.',
  setmail: 'Reads a mailbox from the signed-in Outlook - no password '+
    'needed.<br><b>Mailbox</b> - e.g. OrderDesk@sea.samsung.com once access '+
    'is granted; blank means your own inbox.<br><b>Lookback</b> - used by the '+
    'first collection only; after that it picks up where it left off.<br>'+
    '<b>Filter</b> - with it off, emails carrying no document (or only '+
    'signature images) are collected too.<br><b>PO number</b> - how the '+
    'number is read out of each email. <b>Number only</b> is for a customer '+
    'who prints it bare (KB Home); it is machine-wide, but the standard rule '+
    'runs first, so labelled mail is unaffected.<br><b>DRM files</b> - only '+
    'used when a PDF cannot be read directly; up to a minute per file, so '+
    'turn it off to fail fast instead.',
  setstorage: 'Original emails stay in Outlook, so old attachments can be '+
    'removed safely. Email history, PO numbers and processing status are '+
    'kept, and every cleanup is written to logs/cleanup.log. <b>0</b> days '+
    'keeps attachments for ever.',
  setsync: '<b>Every N minutes</b> is the recommended one - it picks new POs '+
    'up quickly. <b>At fixed times</b> takes up to two times a day: leave the '+
    'second one blank for once a day. <b>Off</b> only syncs when you press '+
    'Save &amp; Collect Now.'
};

// The API card quotes the endpoint it resolved, so its text is built at render
// time rather than written once above.
function apiFaqText(CL){
  return 'DeepSeek reads each locally rendered PDF page as an image. Nothing '+
    'is sent without an API key.<br>'+
    '<b>Endpoint</b> - where a PO is sent. Blank uses '+
    (CL.base_url ? '<code>'+esc(CL.base_url)+'</code>' : 'the built-in address')+
    ', and the <code>/v1/messages</code> path is added for you, so the root is '+
    'enough.<br><b>Model</b> - <code>deepseek-flash</code> is required for '+
    'PDF page images. Every code is still confirmed against the Material '+
    'Code list afterwards.<br><b>API key</b> - sent as '+
    '<code>x-api-key</code>, stored in '+
    '<code>config/settings.json</code> and never shown again; leave blank to '+
    'keep the stored one. The <b>Material Code list still decides</b> which '+
    'codes are published - a code it does not carry is set aside for you, '+
    'never guessed.'+
    (CL.key_set ? '' :
      ' <b>No DeepSeek API key is stored yet, so no PO can be read.</b>');
}

function faq(key, label){
  const t = FAQ[key];
  if (!t) return '';
  // Screen readers get the explanation itself, not just "what this is": the
  // bubble is a separate element, so an aria-label of the first 140 characters
  // is the only version of the text they can reach from the marker.
  const plain = String(label || t)
    .replace(/&quot;/g, '"').replace(/&rarr;/g, '->').replace(/&amp;/g, '&')
    .replace(/<[^>]*>/g, ' ').replace(/\\s+/g, ' ').trim().slice(0, 140);
  // stopPropagation: several markers sit inside a <label> (the ship-to grid),
  // where a click would otherwise be forwarded to the input and open a date
  // picker. The marker explains the field, it does not stand in for it.
  return '<span class="faq" tabindex="0" role="note" data-faq="'+esc(key)+
    '" aria-label="'+esc(plain)+'" '+
    'onclick="event.preventDefault();event.stopPropagation()">'+FAQ_ICON+
    '</span>';
}

// The marker in the page head. One per list, and the Read tab keeps its own
// even while a reading or a preview is open - that prose describes the tab, and
// the tab is still what you are on.
const SCREEN_FAQ = {notmypo:'discarded'};
function screenFaq(){
  if (TAB === 'today'){
    if (ITAB === 2) return 'read';
    if (ITAB === 3) return 'output';
    return 'inbox';
  }
  return SCREEN_FAQ[TAB] || '';
}

// ── The buttons' hover tooltip ────────────────────────────────────────────
// One shared element, positioned against whatever button is hovered. The
// snippet puts a tooltip INSIDE each button, which cannot work here: half of
// these buttons sit inside a .card, and .card has overflow:hidden to round its
// corners - the tooltip would be sliced off at the card edge.
let TIP_EL = null;

function tipEl(){
  if (!TIP_EL){
    TIP_EL = document.createElement('div');
    TIP_EL.className = 'btntip';
    document.body.appendChild(TIP_EL);
  }
  return TIP_EL;
}

function showBtnTip(btn){
  // data-tip is what initBtnTips() moves the title into, but buttons injected
  // later (the Master Data pagers fetch their HTML) never go through it - so a
  // live `title` is adopted on first hover and removed at the same moment, which
  // is what keeps the browser's own tooltip from appearing beside ours.
  let text = btn.getAttribute('data-tip');
  if (!text){
    text = btn.getAttribute('title');
    if (!text) return;
    btn.setAttribute('data-tip', text);
    btn.removeAttribute('title');
  }
  if (!btn.getBoundingClientRect) return;
  const t = tipEl();
  t.textContent = text;
  t.classList.remove('below');
  // The bubble is shared, so a plain label must not inherit the rich layout or
  // an arrow offset left over from the last FAQ marker it showed.
  t.classList.remove('rich');
  t.style.removeProperty('--arrow');
  t.classList.add('on');
  const r = btn.getBoundingClientRect();
  // Centre the bubble on the button, but pull it back inside the window and
  // move the arrow instead of letting it hang off the edge - the same trick
  // showFaqTip() uses.
  const half = t.offsetWidth / 2;
  const cx = Math.max(12 + half,
    Math.min(window.innerWidth - 12 - half, r.left + r.width / 2));
  t.style.left = Math.round(cx) + 'px';
  t.style.top = Math.round(r.top - 9) + 'px';
  t.style.setProperty('--arrow',
    Math.round(r.left + r.width / 2 - (cx - half)) + 'px');
  // Flip underneath when there is no room above - the filter row sits close to
  // the top of the page and its tooltip would be pushed off-screen.
  if (r.top - 9 - t.offsetHeight < 4){
    t.classList.add('below');
    t.style.top = Math.round(r.bottom + 9) + 'px';
  }
}

// The same bubble, in its explaining-a-screen layout. Entries are plain
// strings: the one card whose text quotes a value (the API endpoint) writes its
// string into the registry while it renders, see apiFaqText().
function showFaqTip(m){
  const key = m.getAttribute('data-faq');
  const text = FAQ[key];
  if (!text) return;
  const t = tipEl();
  t.classList.remove('below');
  t.classList.add('rich', 'on');
  t.innerHTML = text;
  const r = m.getBoundingClientRect();
  const half = t.offsetWidth / 2;
  // A 340px bubble centred on a marker near the window edge would hang off it.
  // Clamp the bubble and move the ARROW instead, so it still points at the
  // marker it belongs to.
  const cx = Math.max(12 + half,
    Math.min(window.innerWidth - 12 - half, r.left + r.width / 2));
  t.style.left = Math.round(cx) + 'px';
  t.style.top = Math.round(r.top - 9) + 'px';
  t.style.setProperty('--arrow',
    Math.round(r.left + r.width / 2 - (cx - half)) + 'px');
  if (r.top - 9 - t.offsetHeight < 4){
    t.classList.add('below');
    t.style.top = Math.round(r.bottom + 9) + 'px';
  }
}

function hideBtnTip(){
  if (TIP_EL) TIP_EL.classList.remove('on');
}

// A `.btn` with a `title` gets it moved to data-tip: leaving both would show the
// browser's own tooltip on top of ours.
function initBtnTips(){
  // .segopt is the Full / Simple label: not a button any more, but it keeps the
  // same bubble so the two formats are still explained on hover.
  document.querySelectorAll('.btn[title], .segopt[title]').forEach(b => {
    const t = b.getAttribute('title');
    if (!t) return;
    b.setAttribute('data-tip', t);
    b.removeAttribute('title');
    if (!b.getAttribute('aria-label')) b.setAttribute('aria-label', t);
  });
}

document.addEventListener('mouseover', e => {
  const el = e.target && e.target.closest ? e.target : null;
  if (!el){ hideBtnTip(); return; }
  const q = el.closest('.faq');
  if (q){ showFaqTip(q); return; }
  const b = el.closest('.btn, .segopt');
  if (b) showBtnTip(b); else hideBtnTip();
});
document.addEventListener('mouseout', e => {
  const t = e.target && e.target.closest
    ? e.target.closest('.faq, .btn, .segopt') : null;
  if (!t) return;
  // Moving between the marker's own icon and its box is not leaving it.
  if (e.relatedTarget && t.contains(e.relatedTarget)) return;
  hideBtnTip();
});
document.addEventListener('focusin', e => {
  const el = e.target && e.target.closest ? e.target : null;
  if (!el){ hideBtnTip(); return; }
  const q = el.closest('.faq');
  if (q){ showFaqTip(q); return; }
  const b = el.closest('.btn, .segopt');
  if (b) showBtnTip(b); else hideBtnTip();
});
document.addEventListener('focusout', hideBtnTip);
// A fixed-position tooltip is left behind by a scroll.
window.addEventListener('scroll', hideBtnTip, true);

// ── Narrow-screen handling: fold the rail away entirely ──────────────────────
// The menu is a hover-expand rail now, so "narrow" no longer means "collapse the
// groups" - it means the page needs those 62px back. Below that width the rail
// is hidden outright and the hamburger is the only way to it; on a wide screen
// the rail is always there and this button is a convenience, not a necessity.
// The rail opens on a CLICK (2026-10-28). Hover used to do it, which is fine
// with a mouse and hostile to everything else: the plate swung open while the
// pointer crossed it on the way to a table, and a keyboard user never got it
// at all. The plate is a real <button> now, so Enter / Space work, and the
// class it toggles is what every "while collapsed" rule in the CSS keys off.
function toggleSidebar(open){
  const sb = document.getElementById('sidebar');
  const btn = document.getElementById('brandbtn');
  if (!sb) return;
  const want = (open === undefined) ? !sb.classList.contains('open') : !!open;
  sb.classList.toggle('open', want);
  if (btn){
    btn.setAttribute('aria-expanded', want ? 'true' : 'false');
    btn.title = want ? 'Close the menu' : 'Open the menu';
  }
}

// Escape closes it, and so does clicking anywhere outside it - the plate
// covers the page while open, so a menu that stays open after you have left it
// is a menu that has to be closed twice.
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') toggleSidebar(false);
});
document.addEventListener('mousedown', e => {
  const sb = document.getElementById('sidebar');
  if (!sb || !sb.classList.contains('open')) return;
  if (sb.contains(e.target)) return;
  toggleSidebar(false);
});

function toggleRail(){
  const l = document.querySelector('.layout');
  l.classList.toggle('railed');
  try { localStorage.setItem('rail',
    l.classList.contains('railed') ? '1' : '0'); } catch (e) {}
  render();
}

(function initRail(){
  let saved = null;
  try { saved = localStorage.getItem('rail'); } catch (e) {}
  if (saved === null ? window.innerWidth < 1120 : saved === '1')
    document.querySelector('.layout').classList.add('railed');
})();

let RESIZE_T = null;
window.addEventListener('resize', () => {
  clearTimeout(RESIZE_T);
  RESIZE_T = setTimeout(() => { if (DATA) render(); }, 150);
});

// The date field is re-created on every render (it lives inside #content), so
// it cannot be bound once at boot any more - the listener is delegated.
document.addEventListener('change', function(e){
  const t = e.target;
  if (!t || t.id !== 'datepick') return;
  SELDATE = t.value || localToday();
  TAB = 'today';
  render();
});

load();

// Auto-sync runs in the background, so refresh the screen periodically too
setInterval(() => {
  if (DATA && TAB !== 'settings' && TAB !== 'codes') load();
}, 60000);
</script>
</body>
</html>
"""


# ==========================================================================
#  SECTION: SIDEBAR
# ==========================================================================
# The menu is a rail: 62px of icons that widens over the page on hover. That
# rules out the two-level `navparent`/`navkids` structure it used to have - a
# collapsed child row would have no icon to show, so it would be a blank 40px
# strip. The groups survive as `navsec` labels, which collapse to a 1px rule.
#
# Icons are lucide (lucide.dev), inlined as SVG paths on purpose: the page has
# no build step and no network dependency, and `stroke="currentColor"` is what
# lets the active row tint its own icon without a second rule per icon.
_ICONS = {
    "inbox":
        '<path d="M22 12h-6l-2 3h-4l-2-3H2"/>'
        '<path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l'
        '-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "check":
        '<path d="M21.8 10A10 10 0 1 1 17 3.34"/>'
        '<path d="m9 11 3 3L22 4"/>',
    "archive":
        '<rect width="20" height="5" x="2" y="3" rx="1"/>'
        '<path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/>'
        '<path d="M10 12h4"/>',
    "zap":
        '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46'
        'l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2'
        'a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
    "users":
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
        '<circle cx="9" cy="7" r="4"/>'
        '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/>'
        '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "barcode":
        '<path d="M3 5v14"/><path d="M8 5v14"/><path d="M12 5v14"/>'
        '<path d="M17 5v14"/><path d="M21 5v14"/>',
    "chart":
        '<path d="M3 3v16a2 2 0 0 0 2 2h16"/>'
        '<path d="m19 9-5 5-4-4-3 3"/>',
    "settings":
        '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25'
        'a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 '
        '2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0'
        '-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25'
        'a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 '
        '1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39'
        'a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74'
        'l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08'
        'a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>'
        '<circle cx="12" cy="12" r="3"/>',
    "reset":
        '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>'
        '<path d="M3 3v5h5"/>',
}

# (section label, [(tab, icon, label, badge id or "")]) - order is the order on
# screen; a section with no items is skipped.
_NAV = [
    ("Inbox", [
        ("today", "inbox", "Inbox", ""),
        ("completed", "check", "Completed", "b-completed"),
        ("notmypo", "archive", "Discarded", "b-notmypo"),
    ]),
    ("Tools", [
        ("quick", "zap", "Quick Convert", ""),
    ]),
    ("Data", [
        ("master", "users", "Customer Master", "b-master"),
        ("codes", "barcode", "Material Codes", ""),
    ]),
    ("Insights", [
        ("history", "chart", "Dashboard", ""),
    ]),
    ("System", [
        ("settings", "settings", "Settings", ""),
    ]),
]


def _nav_icon(name: str) -> str:
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
            'aria-hidden="true">%s</svg>' % _ICONS.get(name, ""))


def nav_html() -> str:
    """The sidebar's rows. Built here rather than typed into PAGE so the icon,
    the label and the tab id cannot drift apart from the `data-tab` the
    dispatcher reads."""
    out = []
    for section, items in _NAV:
        if not items:
            continue
        out.append('<div class="navsec">%s</div>' % section)
        for tab, icon, label, badge in items:
            badge_html = ('<span class="badge zero" id="%s">0</span>' % badge
                          if badge else "")
            out.append(
                '<button class="navbtn" data-tab="%s" title="%s">'
                '<span class="nic">%s</span>'
                '<span class="nlb">%s</span>%s</button>'
                % (tab, label, _nav_icon(icon), label, badge_html))
    out.append('<div class="navspacer"></div>')
    out.append(
        '<div class="railfoot">'
        '<div class="syncbox" id="syncbox"></div>'
        '<button class="rstrow" title="Reset all settings to their defaults" '
        'onclick="resetAllSettings()">'
        '<span class="nic">%s</span>'
        '<span class="nlb">Reset settings</span></button>'
        '</div>' % _nav_icon("reset"))
    return "\n      ".join(out)


def render_page():
    try:
        import version
        # build_id(), not version.BUILD: the stamp is re-derived per render, so
        # editing a source file and reloading the page is enough - no restart,
        # and no release step. It costs a handful of stats (see version.py).
        build = version.build_id()
    except Exception:
        build = "dev"
    return (PAGE.replace("__NAV__", nav_html())
                .replace("__BUILD__", build))
