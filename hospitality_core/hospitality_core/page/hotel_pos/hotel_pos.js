frappe.pages['hotel-pos'].on_page_load = function(wrapper) {
    frappe.ui.make_app_page({ parent: wrapper, title: 'Hotel POS', single_column: true });

    // Inline CSS
    if(!document.getElementById('hpos-styles')){
        var s = document.createElement('style');
        s.id = 'hpos-styles';
        s.textContent = [
/* Hotel POS.
 *
 * Everything is scoped under .hpos and built on Frappe's design tokens, so the page
 * follows the active theme (dark mode included) and nothing leaks into the rest of the
 * desk. The previous version declared its own palette on :root and pulled Inter from
 * Google Fonts, which overrode desk variables globally and cost a network round trip
 * on every load.
 *
 * Density is deliberate: a front desk works this screen with a guest waiting, so the
 * room grid fits more per screen and the type/rate/capacity of a room are readable
 * without leaning in. */
/* Indigo as the single decisive colour: selection, primary actions, focus. It is
 * saturated on purpose — selecting a room is the one thing that happens on this screen
 * over and over, and it should be unmistakable from across a desk.
 *
 * Room types get their own hue from an eight-colour ramp so the grid can be scanned by
 * type. Those are identity, never state: they sit on the card's left edge and in the
 * type label, and they never touch the border or fill that mean "selected". The green
 * and red availability dots stay the only semantic colours. */
".hpos{--p:#4f46e5;--p-lift:#6366f1;--p-deep:#4338ca;--p-soft:#eef2ff;--p-line:#c7d2fe;" +
  "--ok:var(--green-500,#22c55e);--bad:var(--red-500,#e24c4c);--warn:var(--orange-500,#f59e0b);" +
  "--card:var(--fg-color,#fff);--sunken:var(--subtle-fg,#f4f5f6);--line:var(--border-color,#e2e8f0);" +
  "--ink:var(--text-color,#1f272e);--dim:var(--text-muted,#6b7684);--r:var(--border-radius-md,8px);" +
  "display:flex;height:calc(100vh - 80px);background:var(--bg-color,#f4f5f6);overflow:hidden;" +
  "color:var(--ink);font-size:var(--text-base,13px)}",
/* On a dark ground the pale tints turn into glare, so they invert to a low-alpha wash. */
"[data-theme='dark'] .hpos{--p:#818cf8;--p-lift:#a5b4fc;--p-deep:#6366f1;" +
  "--p-soft:rgba(129,140,248,.14);--p-line:rgba(129,140,248,.42)}",

/* Room-type ramp. Distinct in hue rather than lightness, so they stay apart for the
   most common colour-vision deficiencies and at a glance on a busy grid. */
".hpos .rt-0{--rt:#4f46e5}.hpos .rt-1{--rt:#0891b2}.hpos .rt-2{--rt:#059669}" +
  ".hpos .rt-3{--rt:#c2410c}.hpos .rt-4{--rt:#7c3aed}.hpos .rt-5{--rt:#0284c7}" +
  ".hpos .rt-6{--rt:#b45309}.hpos .rt-7{--rt:#be185d}",
".hpos-room .rm-type{color:var(--rt,var(--dim))}",
".hpos *{box-sizing:border-box}",
".hpos-left{flex:1;min-width:0;display:flex;flex-direction:column;overflow:hidden}",
".hpos-right{width:360px;flex:0 0 360px;background:var(--card);border-left:1px solid var(--line);" +
  "border-top:2px solid var(--p);" +
  "display:flex;flex-direction:column;min-height:0;overflow:hidden}",

/* Both panes are header / scrolling body / pinned footer, so both have to be flex
   columns themselves. min-height:0 is the part that actually matters: a flex item
   defaults to min-height:auto, which makes it grow to fit its content and silently
   disables the overflow-y:auto on .cart-body inside it. */
"#pos-cart-pane,#pos-arr-detail{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}",
"#pos-cart-pane.pane-hidden,#pos-arr-detail.pane-hidden{display:none}",
/* ---------------------------------------------------------------- guests board */
"#pos-stay-detail{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}",
"#pos-stay-detail.pane-hidden{display:none}",
".hpos-stays{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;overflow:hidden}",
".st-bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px 16px;background:var(--card);" +
  "border-bottom:1px solid var(--line);flex:0 0 auto}",
".st-bar input{flex:1 1 200px;height:32px;padding:0 10px;border:1px solid var(--line);border-radius:var(--border-radius,6px);" +
  "font-size:var(--text-sm,12px);font-family:inherit;background:var(--control-bg,var(--card));color:var(--ink)}",
".st-chips{display:flex;gap:6px;flex-wrap:wrap;padding:8px 16px;background:var(--card);border-bottom:1px solid var(--line);flex:0 0 auto}",
".st-chip{padding:4px 11px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--dim);" +
  "font-size:var(--text-sm,12px);font-weight:500;cursor:pointer;font-family:inherit;white-space:nowrap}",
".st-chip b{font-variant-numeric:tabular-nums;margin-left:3px}",
".st-chip.active{background:var(--p);border-color:var(--p);color:#fff;font-weight:600}",
"#pos-stay-list{flex:1 1 auto;min-height:0;overflow-y:auto;padding:8px 16px 16px}",
".st-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;padding:10px 12px;background:var(--card);" +
  "border:1px solid var(--line);border-left:3px solid var(--line);border-radius:var(--r);margin-bottom:6px;cursor:pointer}",
".st-row:hover{border-color:var(--p-line)}",
".st-row.active{border-color:var(--p);box-shadow:inset 0 0 0 1px var(--p);background:var(--p-soft)}",
".st-row.s-in{border-left-color:var(--bad)}.st-row.s-arr{border-left-color:var(--warn)}.st-row.s-up{border-left-color:var(--p-line)}",
".st-name{font-weight:600;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
".st-meta{font-size:var(--text-xs,11px);color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
".st-side{text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:3px}",
".st-stage{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;padding:1px 7px;border-radius:4px;" +
  "background:var(--sunken);color:var(--dim);white-space:nowrap}",
".st-stage.g-due,.st-stage.g-over{background:var(--bad);color:#fff}",
".st-stage.g-in{background:var(--bg-red,#fdecec);color:var(--bad)}",
".st-stage.g-arr,.st-stage.g-late{background:var(--warn);color:#fff}",
".st-stage.g-hold{background:var(--p-soft);color:var(--p-deep)}",
".st-due{font-size:var(--text-xs,11px);font-weight:600;font-variant-numeric:tabular-nums;color:var(--bad)}",
".st-due.zero{color:var(--ok)}",
".sd-money{background:var(--sunken);border-radius:var(--r);padding:10px 12px;margin:10px 0}",
".sd-money div{display:flex;justify-content:space-between;font-size:var(--text-sm,12px);padding:2px 0;font-variant-numeric:tabular-nums}",
".sd-money .big{font-size:var(--text-lg,15px);font-weight:700;border-top:1px solid var(--line);margin-top:4px;padding-top:6px}",
".sd-money .ok{color:var(--ok)}",
".sd-actions{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px}",
".sd-actions button{height:34px;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:var(--border-radius,6px);" +
  "font-size:var(--text-sm,12px);font-weight:600;cursor:pointer;font-family:inherit}",
".sd-actions button:hover{border-color:var(--p);color:var(--p)}",
".sd-actions button.danger{color:var(--bad)}",
".sd-actions button.danger:hover{border-color:var(--bad)}",
".sd-lines{margin-top:12px;font-size:var(--text-xs,11px)}",
".sd-lines div{display:flex;justify-content:space-between;gap:8px;padding:4px 0;border-bottom:1px dashed var(--line)}",
".sd-lines div span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--dim)}",
".sd-lines .cr{color:var(--ok)}",

/* ---------------------------------------------------------------- topbar */
".hpos-topbar{display:flex;align-items:center;gap:10px;padding:10px 16px;background:var(--card);" +
  "border-bottom:1px solid var(--line);flex:0 0 auto}",
".hpos-topbar .logo-icon{width:32px;height:32px;border-radius:6px;display:flex;align-items:center;" +
  "justify-content:center;overflow:hidden;background:#fff;flex:0 0 auto}",
".hpos-topbar .logo-icon img{width:100%;height:100%;object-fit:contain;display:block}",
".hpos-topbar h2{margin:0;font-size:var(--text-lg,15px);font-weight:600;color:var(--ink);line-height:1.2}",
".hpos-topbar .subtitle{font-size:var(--text-xs,11px);color:var(--dim);margin:1px 0 0}",

/* Mode switcher had no styling at all, so it rendered as two browser default buttons. */
".hpos-modes{margin-left:auto;display:flex;gap:2px;background:var(--sunken);padding:2px;border-radius:var(--r)}",
".hpos-mode{border:0;background:transparent;border-radius:calc(var(--r) - 2px);padding:5px 14px;" +
  "font-size:var(--text-sm,12px);font-weight:500;color:var(--dim);cursor:pointer;font-family:inherit;" +
  "white-space:nowrap;transition:background .12s,color .12s}",
".hpos-mode:hover{color:var(--ink)}",
".hpos-mode.active{background:var(--card);color:var(--ink);font-weight:600;box-shadow:var(--shadow-sm,0 1px 2px rgba(0,0,0,.08))}",

/* ---------------------------------------------------------------- filter bar */
".hpos-filters{display:flex;gap:10px;padding:10px 16px;background:var(--card);" +
  "border-bottom:1px solid var(--line);align-items:flex-end;flex-wrap:wrap;flex:0 0 auto}",
".hpos-fg{display:flex;flex-direction:column;gap:3px;min-width:0}",
".hpos-fg label{font-size:var(--text-xs,11px);font-weight:500;color:var(--dim);" +
  "text-transform:uppercase;letter-spacing:.03em;margin:0}",
".hpos-fg input{height:30px;padding:0 9px;border:1px solid var(--line);border-radius:var(--border-radius,6px);" +
  "font-size:var(--text-sm,12px);font-family:inherit;background:var(--control-bg,var(--card));color:var(--ink)}",
".hpos-fg input:focus{outline:none;border-color:var(--p);box-shadow:0 0 0 2px var(--awesomebar-focus-bg,rgba(36,144,239,.16))}",
".hpos-btn{height:30px;padding:0 14px;border:none;border-radius:var(--border-radius,6px);" +
  "font-size:var(--text-sm,12px);font-weight:600;cursor:pointer;font-family:inherit}",
".hpos-btn-primary{background:var(--p);color:#fff}",
".hpos-btn-primary:hover{filter:brightness(.94)}",

/* ---------------------------------------------------------------- stats */
".hpos-stats{display:flex;gap:8px;padding:8px 16px;background:var(--card);" +
  "border-bottom:1px solid var(--line);flex:0 0 auto}",
".hpos-stat{flex:1;display:flex;align-items:baseline;justify-content:center;gap:6px;padding:6px 8px;" +
  "border-radius:var(--border-radius,6px);background:var(--sunken);min-width:0}",
".hpos-stat .num{font-size:var(--text-lg,15px);font-weight:700;color:var(--ink);line-height:1;" +
  "font-variant-numeric:tabular-nums}",
".hpos-stat .lbl{font-size:var(--text-xs,11px);color:var(--dim);text-transform:uppercase;" +
  "letter-spacing:.03em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
".hpos-stat.stat-green .num{color:var(--ok)}",
".hpos-stat.stat-red .num{color:var(--bad)}",
".hpos-stat.stat-blue .num{color:var(--p)}",

/* ---------------------------------------------------------------- type tabs */
".hpos-type-tabs{display:flex;gap:6px;padding:8px 16px;overflow-x:auto;background:var(--card);" +
  "border-bottom:1px solid var(--line);flex:0 0 auto;scrollbar-width:thin}",
".hpos-type-tabs::-webkit-scrollbar{height:4px}",
".hpos-type-tabs::-webkit-scrollbar-thumb{background:var(--line);border-radius:4px}",
".hpos-tab{padding:4px 12px;border-radius:var(--border-radius-full,999px);font-size:var(--text-sm,12px);" +
  "font-weight:500;cursor:pointer;border:1px solid var(--line);background:transparent;color:var(--dim);" +
  "white-space:nowrap;font-family:inherit;transition:border-color .12s,color .12s}",
".hpos-tab:hover{border-color:var(--p-line);color:var(--p)}",
".hpos-tab.active{background:var(--p);color:#fff;border-color:var(--p);font-weight:600;" +
  "box-shadow:0 1px 6px rgba(79,70,229,.32)}",

/* ---------------------------------------------------------------- room grid */
".hpos-grid{flex:1 1 auto;min-height:0;padding:12px 16px;overflow-y:auto;display:grid;" +
  "grid-template-columns:repeat(auto-fill,minmax(184px,1fr));gap:10px;align-content:start}",

/* Fixed row height plus a column layout is what stops the cards going ragged when one
   room has a weekend rate or an extra badge and its neighbour does not. */
/* The room name kept disappearing, and this is why: .rm-num and .rm-type set
   overflow:hidden to get a horizontal ellipsis, and overflow:hidden gives a flex item an
   automatic minimum size of ZERO. So when grid stretch pinned the card to the row height
   and the content did not fit, those two were the only children able to give — they
   collapsed vertically and clipped their own text. The card looked empty at the top.

   "flex:0 0 auto" on every child is the fix: nothing shrinks, so the card grows to its
   content and the ellipsis stays a horizontal concern only. */
".hpos-room{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--rt,var(--line));" +
  "border-radius:var(--r);padding:11px 12px;cursor:pointer;position:relative;display:flex;" +
  "flex-direction:column;gap:4px;transition:border-color .12s,box-shadow .12s,background .12s}",
".hpos-room > *{flex:0 0 auto;min-height:0}",
".hpos-room:hover:not(.off){border-color:var(--p-line);box-shadow:0 2px 10px rgba(0,0,0,.07)}",
".hpos-room.sel{border-color:var(--p);border-left-color:var(--p);background:var(--p-soft);" +
  "box-shadow:inset 0 0 0 1px var(--p),0 2px 8px rgba(79,70,229,.18)}",
".hpos-room.sel .rm-type{color:var(--p-deep)}",
".hpos-room.sel::after{content:'\\2713';position:absolute;top:8px;right:9px;width:17px;height:17px;" +
  "background:var(--p);color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;" +
  "font-size:11px;font-weight:700;box-shadow:0 1px 4px rgba(79,70,229,.5)}",
/* Occupied (checked in) and Reserved (booked or held, not yet arrived) are different
   jobs for the desk — check out vs check in — so they read differently. Both are
   clickable: the card opens what can be done with that guest. */
".hpos-room.occ{background:var(--sunken);border-left-color:var(--bad)}",
".hpos-room.rsv{background:var(--bg-orange,#fff7ed);border-left-color:var(--warn);border-style:solid}",
".hpos-room.occ .rm-rate,.hpos-room.rsv .rm-rate,.hpos-room.occ .rm-amen,.hpos-room.rsv .rm-amen{opacity:.55}",
".hpos-room .rm-who{font-size:var(--text-xs,11px);font-weight:600;color:var(--ink);white-space:nowrap;" +
  "overflow:hidden;text-overflow:ellipsis}",
".hpos-room .rm-when{font-size:var(--text-xs,11px);color:var(--dim)}",
".hpos-room .rm-flag{display:inline-block;font-size:10px;font-weight:700;text-transform:uppercase;" +
  "letter-spacing:.03em;border-radius:4px;padding:0 5px;margin-right:4px}",
".rm-flag.in{background:var(--bad);color:#fff}",
".rm-flag.rs{background:var(--warn);color:#fff}",
".hpos-tab .held{font-size:10px;margin-left:4px;opacity:.8}",
".dot-rsv{background:var(--warn)}",
".hpos-stat.stat-amber .num{color:var(--warn)}",
".cart-check{display:flex;align-items:center;gap:8px;font-size:var(--text-sm,12px);font-weight:600;" +
  "color:var(--ink);margin:6px 0 2px;cursor:pointer}",
".cart-check input{width:16px;height:16px;margin:0}",
".hpos-room.off{opacity:.45;cursor:not-allowed;border-style:dashed}",
".hpos-room .rm-num{font-size:var(--text-base,13px);font-weight:600;color:var(--ink);line-height:1.25;" +
  "padding-right:20px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
".hpos-room .rm-type{font-size:var(--text-xs,11px);color:var(--dim);line-height:1.3;" +
  "overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
".hpos-room .rm-rate{margin-top:2px;font-size:var(--text-base,13px);font-weight:600;color:var(--ink);" +
  "font-variant-numeric:tabular-nums}",
".hpos-room .rm-rate span{font-size:var(--text-xs,11px);font-weight:400;color:var(--dim)}",
".hpos-room .rm-dot{position:absolute;bottom:11px;right:11px;width:7px;height:7px;border-radius:50%}",
".hpos-room .rm-meta{display:flex;align-items:center;gap:4px;flex-wrap:wrap}",
".rm-cap{display:inline-flex;align-items:center;gap:3px;font-size:var(--text-xs,11px);font-weight:600;" +
  "color:var(--p-deep);background:var(--p-soft);border-radius:var(--border-radius-full,999px);padding:1px 7px}",
".rm-bed{display:inline-flex;align-items:center;font-size:var(--text-xs,11px);color:var(--dim);" +
  "background:var(--sunken);border-radius:var(--border-radius-full,999px);padding:1px 7px}",
".rm-amen{display:flex;gap:3px;flex-wrap:wrap}",
".rm-amen i{font-style:normal;font-size:11px;line-height:1;opacity:.8;cursor:help}",
".rm-wknd{display:block;font-size:var(--text-xs,11px);color:var(--warn);font-weight:500}",
".rm-stay{display:block;font-size:var(--text-xs,11px);color:var(--dim)}",
".dot-avail{background:var(--ok)}",
".dot-occ{background:var(--bad)}",
".dot-maint{background:var(--warn)}",

/* ---------------------------------------------------------------- cart */
".cart-hdr{flex:0 0 auto;padding:12px 16px;border-bottom:1px solid var(--line)}",
".cart-hdr h3{margin:0;font-size:var(--text-base,13px);font-weight:600;color:var(--ink)}",
".cart-hdr .nights{font-size:var(--text-xs,11px);color:var(--dim);margin-top:1px}",
".cart-body{flex:1 1 auto;min-height:0;overflow-y:auto;padding:12px 16px}",
".cart-sec{font-size:var(--text-xs,11px);font-weight:600;color:var(--dim);text-transform:uppercase;" +
  "letter-spacing:.03em;margin:14px 0 7px}",
".cart-sec:first-child{margin-top:0}",
".cart-item{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;padding:8px 0;" +
  "border-bottom:1px solid var(--line)}",
".cart-item:last-child{border-bottom:none}",
".ci-name{font-size:var(--text-base,13px);font-weight:600;color:var(--ink)}",
".ci-sub{font-size:var(--text-xs,11px);color:var(--dim);margin-top:1px}",
".ci-price{font-size:var(--text-base,13px);font-weight:600;color:var(--ink);white-space:nowrap;" +
  "font-variant-numeric:tabular-nums}",
".ci-rm{color:var(--bad);cursor:pointer;margin-left:6px;font-size:var(--text-xs,11px);padding:1px 6px;" +
  "border-radius:4px;border:1px solid var(--line);background:transparent;font-family:inherit}",
".ci-rm:hover{border-color:var(--bad);background:var(--bg-red,#fce9e9)}",
".ci-warn{font-size:var(--text-xs,11px);color:var(--bad);margin-top:3px;font-weight:500}",
".ci-amen{font-size:var(--text-xs,11px);color:var(--dim);margin-top:2px}",
/* Over capacity is a priced sale, not a fault — reads as information, not as an error. */
".ci-info{font-size:var(--text-xs,11px);color:var(--warn);background:var(--bg-amber,#fff7ed);" +
  "border-radius:4px;padding:5px 8px;margin-top:6px;font-weight:500}",
".cart-note{font-size:var(--text-xs,11px);color:var(--dim);padding-top:8px;" +
  "border-top:1px dashed var(--line);margin-top:8px}",
/* Was a block icon followed by a bare text node, which collided at large font sizes. */
".cart-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;" +
  "text-align:center;padding:32px 16px;color:var(--dim);font-size:var(--text-sm,12px)}",
".cart-empty .icon{font-size:26px;line-height:1;opacity:.35;margin:0}",

/* ---------------------------------------------------------------- guest form */
".guest-toggle{width:100%;padding:7px;border:1px dashed var(--line);border-radius:var(--border-radius,6px);" +
  "background:transparent;color:var(--p);font-size:var(--text-sm,12px);font-weight:600;cursor:pointer;" +
  "font-family:inherit;margin-bottom:10px}",
".guest-toggle:hover{background:var(--p-soft);border-color:var(--p-line)}",
".guest-form{background:var(--sunken);padding:12px;border-radius:var(--r);display:none}",
".gf-row{margin-bottom:8px}",
".gf-row:last-child{margin-bottom:0}",
".gf-row label{font-size:var(--text-xs,11px);font-weight:500;color:var(--dim);text-transform:uppercase;" +
  "display:block;margin-bottom:2px}",
".gf-row input,.gf-row select{width:100%;height:30px;padding:0 9px;border:1px solid var(--line);" +
  "border-radius:var(--border-radius,6px);font-size:var(--text-sm,12px);font-family:inherit;" +
  "background:var(--control-bg,var(--card));color:var(--ink)}",
".gf-row input:focus,.gf-row select:focus{outline:none;border-color:var(--p);" +
  "box-shadow:0 0 0 2px var(--awesomebar-focus-bg,rgba(36,144,239,.16))}",
/* The guest Link control is a real Frappe control; it rendered as a bare grey block
   because nothing here gave it a border. Match the hand-rolled inputs beside it. */
"#guest-link-wrapper .frappe-control{margin:0 0 10px}",
"#guest-link-wrapper .control-label{font-size:var(--text-xs,11px);font-weight:500;color:var(--dim);" +
  "text-transform:uppercase;margin-bottom:2px}",
"#guest-link-wrapper .control-input input{height:30px;border:1px solid var(--line);" +
  "border-radius:var(--border-radius,6px);font-size:var(--text-sm,12px);background:var(--control-bg,var(--card))}",

/* ---------------------------------------------------------------- footer */
".cart-footer{flex:0 0 auto;padding:12px 16px;background:var(--card);border-top:1px solid var(--line)}",
".cart-total{display:flex;justify-content:space-between;align-items:baseline;font-size:var(--text-lg,15px);" +
  "font-weight:700;color:var(--ink);margin-bottom:9px;font-variant-numeric:tabular-nums}",
".cart-total span:last-child{color:var(--p-deep)}",
".btn-book{width:100%;padding:11px;background:linear-gradient(180deg,var(--p-lift),var(--p));color:#fff;border:none;" +
  "border-radius:var(--border-radius,6px);font-size:var(--text-base,13px);font-weight:600;cursor:pointer;" +
  "font-family:inherit;transition:filter .12s}",
".btn-book:hover:not(:disabled){filter:brightness(1.06);box-shadow:0 3px 12px rgba(79,70,229,.34)}",
".btn-book:disabled{opacity:.45;cursor:not-allowed}",

/* ---------------------------------------------------------------- arrivals (was entirely unstyled) */
".hpos-arrivals{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;overflow:hidden}",
".hpos-arr-search{padding:10px 16px;border-bottom:1px solid var(--line);background:var(--card);flex:0 0 auto}",
".hpos-arr-search input{width:100%;height:32px;padding:0 10px;border:1px solid var(--line);" +
  "border-radius:var(--border-radius,6px);font-size:var(--text-sm,12px);font-family:inherit;" +
  "background:var(--control-bg,var(--card));color:var(--ink)}",
".hpos-arr-search input:focus{outline:none;border-color:var(--p);" +
  "box-shadow:0 0 0 2px var(--awesomebar-focus-bg,rgba(36,144,239,.16))}",
"#pos-arr-list{flex:1 1 auto;min-height:0;overflow-y:auto;padding:8px 16px 16px}",
".arr-row{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:10px 12px;" +
  "background:var(--card);border:1px solid var(--line);border-radius:var(--r);margin-bottom:6px;" +
  "cursor:pointer;transition:border-color .12s}",
".arr-row:hover{border-color:var(--p-line)}",
".arr-row.active{border-color:var(--p);box-shadow:inset 0 0 0 1px var(--p);background:var(--p-soft)}",
".arr-main{min-width:0;flex:1 1 auto}",
".arr-name{font-size:var(--text-base,13px);font-weight:600;color:var(--ink);" +
  "overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
".arr-meta{font-size:var(--text-xs,11px);color:var(--dim);margin-top:1px;" +
  "overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
".arr-side{flex:0 0 auto;text-align:right}",
".arr-status{display:inline-block;font-size:var(--text-xs,11px);font-weight:600;padding:2px 8px;" +
  "border-radius:var(--border-radius-full,999px);background:var(--sunken);color:var(--dim);white-space:nowrap}",
".arr-confirmed{background:var(--bg-green,#e6f5ea);color:var(--text-on-green,#15803d)}",
".arr-tentative{background:var(--bg-orange,#fff3e0);color:var(--text-on-orange,#b45309)}",
".arr-checkedin{background:var(--p-soft);color:var(--p-deep)}",
".arr-walkin{background:var(--bg-light-gray,var(--sunken));color:var(--dim)}",
".arr-tag{display:inline-block;font-size:var(--text-xs,11px);color:var(--dim);margin-top:3px}",
".arr-lines{margin-bottom:4px}",
".arr-line{display:flex;justify-content:space-between;gap:8px;padding:6px 0;" +
  "border-bottom:1px solid var(--line);font-size:var(--text-sm,12px)}",
".arr-line:last-child{border-bottom:none}",
".arr-room-pick{height:28px;border:1px solid var(--line);border-radius:var(--border-radius,6px);" +
  "font-size:var(--text-sm,12px);font-family:inherit;background:var(--control-bg,var(--card));color:var(--ink);padding:0 6px}",
".arr-room-fixed{font-size:var(--text-sm,12px);color:var(--ink);font-weight:500}",
".arr-room-none{font-size:var(--text-xs,11px);color:var(--bad)}",
".arr-note{font-size:var(--text-xs,11px);color:var(--dim);background:var(--sunken);padding:7px 9px;" +
  "border-radius:var(--border-radius,6px);margin-top:6px}",
".arr-money{display:flex;justify-content:space-between;font-size:var(--text-sm,12px);padding:4px 0;" +
  "color:var(--ink);font-variant-numeric:tabular-nums}",
".arr-money-adv{color:var(--ok)}",
".arr-money-due{font-weight:700;font-size:var(--text-base,13px);border-top:1px solid var(--line);" +
  "margin-top:4px;padding-top:7px}",
".arr-adv{color:var(--ok);font-weight:600}",
".arr-due{color:var(--bad);font-weight:600}",

/* ---------------------------------------------------------------- narrow screens */
"@media (max-width:1100px){.hpos-right{width:300px;flex-basis:300px}" +
  ".hpos-grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}}"
].join("\n");
        document.head.appendChild(s);
    }

    var $main = $(wrapper).find('.layout-main-section');
    $main.html(build_layout());

    // Dates show as dd/mm/yy; the value the server gets stays YYYY-MM-DD (data-iso).
    init_pos_date('#pos-arr', function(iso){
        // Check-out always after check-in: move it on if check-in passes it.
        if(iso >= pos_date_val('#pos-dep')){ set_pos_date('#pos-dep', frappe.datetime.add_days(iso, 1)); }
    });
    init_pos_date('#pos-dep', function(iso){
        if(iso <= pos_date_val('#pos-arr')){ set_pos_date('#pos-dep', frappe.datetime.add_days(pos_date_val('#pos-arr'), 1)); }
    });
    init_pos_date('#pos-arr-date');
    $(wrapper).find('.page-head').hide();

    // Setup guest link field
    var guest_field = frappe.ui.form.make_control({
        parent: $('#guest-link-wrapper'),
        df: { fieldtype:'Link', options:'Guest', fieldname:'sel_guest', label:'Search Guest (Name / Phone)',
              onchange: function(){ POS.state.selected_guest = this.get_value(); POS.refresh_btn(); }},
        render_input: true
    });
    guest_field.make_input();

    // POS App
    var POS = {
        state: { rooms:[], room_types:[], cart:[], selected_guest:null, is_new_guest:false,
                 arrival: frappe.datetime.now_date(),
                 departure: frappe.datetime.add_days(frappe.datetime.now_date(),1),
                 arrival_time: '',
                 departure_time: '',
                 nights:1, filter_type:'All', mode:'new', arrival_doc:null,
                 adults:1, children:0,
                 rate_override:0, discount_type:'', discount_value:0 },

        init: function(){
            this.bind();
            this.load();
            // Payment modes come from the site, not a hard-coded list.
            frappe.db.get_list('Mode of Payment', {filters:{enabled:1}, fields:['name'], limit: 50})
                .then(function(rows){
                    if(!rows || !rows.length) return;
                    $('#pos-mop').html(rows.map(function(m){
                        var n = frappe.utils.escape_html(m.name);
                        return '<option'+(m.name==='Cash'?' selected':'')+'>'+n+'</option>';
                    }).join(''));
                });
        },

        bind: function(){
            var self = this;
            $('#pos-search-btn').on('click', function(){ self.on_search(); });
            // Party size drives the capacity warning in the cart, so keep state in
            // step as it is typed rather than only reading it at checkout.
            $('#pos-adults, #pos-children').on('input change', function(){
                self.state.adults = cint($('#pos-adults').val());
                self.state.children = cint($('#pos-children').val());
                self.render_cart();
            });
            // An agreed rate or discount typed at the desk changes the total the guest
            // is quoted, so recompute the cart as it is entered.
            $('#pos-rate-override, #pos-discount-type, #pos-discount-value')
                .on('input change', function(){
                    self.state.rate_override = flt($('#pos-rate-override').val());
                    self.state.discount_type = $('#pos-discount-type').val() || '';
                    self.state.discount_value = flt($('#pos-discount-value').val());
                    self.render_cart();
                });
            $('#btn-new-guest').on('click', function(){
                self.state.is_new_guest = !self.state.is_new_guest;
                if(self.state.is_new_guest){
                    $('#new-guest-form').slideDown(200);
                    $('#guest-link-wrapper').hide();
                    $(this).text('Cancel');
                    guest_field.set_value('');
                } else {
                    $('#new-guest-form').slideUp(200);
                    $('#guest-link-wrapper').show();
                    $(this).text('+ New Guest');
                }
                self.refresh_btn();
            });
            $('#btn-confirm').on('click', function(){ self.book(); });
            $('#pos-checkin-now').on('change', function(){ self.refresh_btn(); });
            $('#new-guest-form').on('input','input', function(){ self.refresh_btn(); });

            $('.hpos-mode').on('click', function(){ self.set_mode($(this).data('mode')); });
            $('#pos-arr-refresh').on('click', function(){ self.load_arrivals(); });
            $('#pos-arr-q').on('keydown', function(e){ if(e.key === 'Enter'){ self.load_arrivals(); } });
            $('#pos-stay-q').on('input', frappe.utils.debounce(function(){ self.load_stays(); }, 250));
            $('#pos-stay-chips').on('click', '.st-chip', function(){
                self.state.stay_view = $(this).data('view');
                self.load_stays();
            });
        },

        // --- Arrivals -------------------------------------------------------
        // The walk-in flow above is untouched. This mode exists because a guest who
        // booked by phone could not be processed here at all: their room reads as
        // Occupied and is un-clickable, and confirming would throw "already booked".
        set_mode: function(mode){
            this.state.mode = mode;
            $('.hpos-mode').removeClass('active');
            $('.hpos-mode[data-mode="'+mode+'"]').addClass('active');

            var arrivals = mode === 'arrivals';
            var stays = mode === 'stays';
            $('#pos-arrivals').toggle(arrivals);
            $('#pos-stays').toggle(stays);
            $('#pos-arr-detail').toggleClass('pane-hidden', !arrivals);
            $('#pos-stay-detail').toggleClass('pane-hidden', !stays);
            $('#pos-grid, #pos-type-tabs, .hpos-filters, .hpos-stats').toggle(mode === 'new');
            $('#pos-cart-pane').toggleClass('pane-hidden', mode !== 'new');

            if(arrivals){ this.load_arrivals(); }
            if(stays){ this.load_stays(); }
            if(mode === 'new'){ this.load(); }
        },

        load_arrivals: function(){
            var self = this;
            $('#pos-arr-list').html('<div class="cart-empty"><div class="icon">⏳</div>Loading arrivals...</div>');
            frappe.call({
                method:'hospitality_core.hospitality_core.page.hotel_pos.hotel_pos.get_arrivals',
                args:{ date: pos_date_val('#pos-arr-date'), search: $('#pos-arr-q').val() },
                callback: function(r){
                    if(r.message){ self.render_arrivals(r.message); }
                }
            });
        },

        render_arrivals: function(data){
            var self = this;
            var rows = [];

            (data.bookings || []).forEach(function(b){
                var advance = b.advance_received ? '<span class="arr-adv">Advance '+format_currency(b.advance_received)+'</span>' : '';
                var due = b.balance_due > 0 ? '<span class="arr-due">Due '+format_currency(b.balance_due)+'</span>' : '';
                rows.push('<div class="arr-row" data-booking="'+b.name+'">'+
                    '<div class="arr-main">'+
                      '<div class="arr-name">'+frappe.utils.escape_html(b.guest_name || b.guest || '')+'</div>'+
                      '<div class="arr-meta">'+frappe.utils.escape_html(b.mobile_no || '')+' · '+b.name+'</div>'+
                      '<div class="arr-meta">'+frappe.datetime.str_to_user(b.arrival_date)+' → '+
                        frappe.datetime.str_to_user(b.departure_date)+' · '+(b.room_count||0)+' room(s)</div>'+
                    '</div>'+
                    '<div class="arr-side"><span class="arr-status arr-'+(b.status||'').toLowerCase().replace(/\s/g,'')+'">'+
                      b.status+'</span>'+advance+due+'</div>'+
                  '</div>');
            });

            (data.reservations || []).forEach(function(r){
                rows.push('<div class="arr-row" data-reservation="'+r.name+'">'+
                    '<div class="arr-main">'+
                      '<div class="arr-name">'+frappe.utils.escape_html(r.guest_name || r.guest || '')+'</div>'+
                      '<div class="arr-meta">'+frappe.utils.escape_html(r.mobile_no || '')+' · '+r.name+'</div>'+
                      '<div class="arr-meta">Room '+(r.room||'-')+' · '+
                        frappe.datetime.str_to_user(r.arrival_date)+'</div>'+
                    '</div>'+
                    '<div class="arr-side"><span class="arr-status arr-walkin">Walk-in</span></div>'+
                  '</div>');
            });

            $('#pos-arr-count').text(rows.length ? '('+rows.length+')' : '');

            if(!rows.length){
                $('#pos-arr-list').html('<div class="cart-empty"><div class="icon">📋</div>No arrivals for this date</div>');
                $('#pos-arr-detail').html('');
                return;
            }
            $('#pos-arr-list').html(rows.join(''));
            $('#pos-arr-list .arr-row').on('click', function(){
                $('#pos-arr-list .arr-row').removeClass('active');
                $(this).addClass('active');
                self.open_arrival($(this).data('booking'), $(this).data('reservation'));
            });
        },

        open_arrival: function(booking, reservation){
            var self = this;
            $('#pos-arr-detail').html('<div class="cart-empty"><div class="icon">⏳</div>Loading...</div>');
            frappe.call({
                method:'hospitality_core.hospitality_core.page.hotel_pos.hotel_pos.get_arrival_detail',
                args:{ booking: booking || null, reservation: reservation || null },
                callback: function(r){
                    if(r.message){ self.state.arrival_doc = r.message; self.render_arrival_detail(r.message); }
                }
            });
        },

        render_arrival_detail: function(d){
            var self = this;
            var rooms = (d.rooms || []).map(function(line){
                var opts = (d.room_options && d.room_options[line.room_type]) || [];
                var cell;
                if(line.room){
                    cell = '<span class="arr-room-fixed">'+frappe.utils.escape_html(line.room)+'</span>';
                } else if(opts.length){
                    cell = '<select class="arr-room-pick" data-idx="'+line.idx+'">'+
                        opts.map(function(o){ return '<option value="'+frappe.utils.escape_html(o)+'">'+
                            frappe.utils.escape_html(o)+'</option>'; }).join('')+'</select>';
                } else {
                    cell = '<span class="arr-room-none">No room free</span>';
                }
                return '<div class="arr-line">'+
                    '<div>'+frappe.utils.escape_html(line.room_type || '')+
                      (line.reservation_status ? ' <span class="arr-tag">'+line.reservation_status+'</span>' : '')+'</div>'+
                    '<div>'+cell+'</div>'+
                  '</div>';
            }).join('');

            var advance = d.unapplied_advance > 0
                ? '<div class="arr-money arr-money-adv"><span>Advance to apply</span><span>'+
                  format_currency(d.unapplied_advance)+'</span></div>' : '';

            $('#pos-arr-detail').html(
                '<div class="cart-hdr"><h3>'+frappe.utils.escape_html(d.guest_name || '')+'</h3>'+
                  '<div class="nights">'+frappe.utils.escape_html(d.mobile_no || '')+'</div></div>'+
                '<div class="cart-body">'+
                  '<div class="cart-sec">'+d.name+' · '+(d.nights || '')+' night(s)</div>'+
                  '<div class="arr-lines">'+rooms+'</div>'+
                  (d.special_requests ? '<div class="arr-note">'+frappe.utils.escape_html(d.special_requests)+'</div>' : '')+
                  '<div class="cart-sec">Money</div>'+
                  '<div class="arr-money"><span>Total</span><span>'+format_currency(d.total_amount||0)+'</span></div>'+
                  '<div class="arr-money"><span>Advance received</span><span>'+format_currency(d.advance_received||0)+'</span></div>'+
                  advance+
                  '<div class="arr-money arr-money-due"><span>Balance due</span><span>'+format_currency(d.balance_due||0)+'</span></div>'+
                '</div>'+
                '<div class="cart-footer">'+
                  '<button class="btn-book" id="btn-checkin">Check In</button>'+
                '</div>'
            );

            $('#btn-checkin').on('click', function(){ self.checkin_arrival(); });
        },

        checkin_arrival: function(){
            var self = this;
            var d = this.state.arrival_doc;
            if(!d){ return; }

            var assignments = {};
            $('#pos-arr-detail .arr-room-pick').each(function(){
                assignments[$(this).data('idx')] = $(this).val();
            });

            var unassigned = (d.rooms || []).filter(function(l){
                return !l.room && !assignments[l.idx];
            });
            if(unassigned.length){
                frappe.msgprint('Every room must be assigned before check-in.');
                return;
            }

            frappe.call({
                method:'hospitality_core.hospitality_core.page.hotel_pos.hotel_pos.checkin_arrival',
                args:{
                    booking: d.type === 'booking' ? d.name : null,
                    reservation: d.type === 'reservation' ? d.name : null,
                    room_assignments: JSON.stringify(assignments)
                },
                freeze: true,
                freeze_message: 'Checking in...',
                callback: function(r){
                    if(!r.message){ return; }
                    var msg = 'Checked in '+(r.message.checked_in || []).length+' room(s)';
                    if(r.message.advance_applied){
                        msg += ' · advance '+format_currency(r.message.advance_applied)+' applied';
                    }
                    frappe.show_alert({message: msg, indicator: 'green'});
                    self.load_arrivals();
                    $('#pos-arr-detail').html('');
                }
            });
        },

        on_search: function(){
            this.state.arrival = pos_date_val('#pos-arr');
            this.state.departure = pos_date_val('#pos-dep');
            // Times are the property's standard check-in/check-out (settings), not typed.
            this.state.arrival_time = '';
            this.state.departure_time = '';
            this.state.adults = cint($('#pos-adults').val());
            this.state.children = cint($('#pos-children').val());
            this.state.nights = frappe.datetime.get_diff(this.state.departure, this.state.arrival);
            if(this.state.nights <= 0){ frappe.msgprint('Departure must be after Arrival.'); return; }
            this.state.cart = [];
            this.load();
        },

        load: function(){
            var self = this;
            $('#pos-grid').html('<div class="cart-empty"><div class="icon">⏳</div>Loading inventory...</div>');
            frappe.call({
                method:'hospitality_core.hospitality_core.page.hotel_pos.hotel_pos.get_pos_data',
                args:{
                    arrival: self.state.arrival,
                    departure: self.state.departure,
                    arrival_time: self.state.arrival_time || '',
                    departure_time: self.state.departure_time || ''
                },
                callback: function(r){
                    if(r.message){
                        self.state.rooms = r.message.rooms || [];
                        self.state.room_types = r.message.room_types || [];
                        self.state.held = r.message.held || {};
                        // The room grid must draw even if a browser is still running an
                        // older shared front_desk.js, so format the time locally if needed.
                        var t = (frappe.hospitality && frappe.hospitality.stay && frappe.hospitality.stay.fmt_time) ||
                            function(v){
                                if(!v) return '';
                                var p = String(v).split(':'), h = parseInt(p[0], 10) || 0, m = parseInt(p[1], 10) || 0;
                                return ((h + 11) % 12 + 1) + ':' + (m < 10 ? '0' : '') + m + (h >= 12 ? ' PM' : ' AM');
                            };
                        $('#pos-stay-times').text(__('Check-in {0} · Check-out {1}', [t(r.message.check_in_time), t(r.message.check_out_time)]));
                        self.render_tabs();
                        self.render_grid();
                        self.render_stats();
                        self.render_cart();
                    }
                }
            });
        },

        render_stats: function(){
            var avail = this.state.rooms.filter(function(r){return r.status==='Available'}).length;
            var occ = this.state.rooms.filter(function(r){return r.status==='Occupied'}).length;
            var rsv = this.state.rooms.filter(function(r){return r.status==='Reserved'}).length;
            var total = this.state.rooms.length;
            // Occupancy for the window counts rooms sold, arrived or not.
            var pct = total ? Math.round((occ + rsv)/total*100) : 0;
            $('#stat-avail').text(avail);
            $('#stat-occ').text(occ);
            $('#stat-rsv').text(rsv);
            $('#stat-pct').text(pct + '%');
            $('#stat-sel').text(this.state.cart.length);
            $('#cart-nights').text(this.state.nights);
        },

        render_tabs: function(){
            var self = this;
            var $tabs = $('#pos-type-tabs');
            $tabs.empty();
            $tabs.append('<button class="hpos-tab'+(self.state.filter_type==='All'?' active':'')+'" data-type="All">All Rooms</button>');
            self.state.room_types.forEach(function(rt){
                // Rooms of this type promised on a booking that has no room number yet.
                var held = (self.state.held || {})[rt.name];
                var badge = held ? '<span class="held" title="'+__('Held on bookings without a room number')+'">('+held+' '+__('held')+')</span>' : '';
                $tabs.append('<button class="hpos-tab'+(self.state.filter_type===rt.name?' active':'')+'" data-type="'+
                    frappe.utils.escape_html(rt.name)+'">'+frappe.utils.escape_html(rt.name)+badge+'</button>');
            });
            $tabs.off('click','.hpos-tab').on('click','.hpos-tab', function(){
                self.state.filter_type = $(this).data('type');
                $tabs.find('.hpos-tab').removeClass('active');
                $(this).addClass('active');
                self.render_grid();
            });
        },

        render_grid: function(){
            var self = this;
            var $grid = $('#pos-grid');
            $grid.empty();
            var filtered = self.state.rooms;
            if(self.state.filter_type !== 'All'){
                filtered = filtered.filter(function(r){ return r.room_type === self.state.filter_type; });
            }
            if(!filtered.length){
                $grid.html('<div class="cart-empty" style="grid-column:1/-1"><div class="icon">🏨</div>No rooms found</div>');
                return;
            }
            filtered.forEach(function(room){
                var is_sel = self.state.cart.some(function(c){return c.name===room.name});
                var cls = 'hpos-room';
                var dot = 'dot-avail';
                if(room.status==='Occupied'){ cls+=' occ'; dot='dot-occ'; }
                else if(room.status==='Reserved'){ cls+=' rsv'; dot='dot-rsv'; }
                else if(room.status==='Maintenance'){ cls+=' off'; dot='dot-maint'; }
                if(is_sel) cls+=' sel';

                // A colour per room type so the grid is scannable by type without reading
                // every label. Taken from the room type's position in the loaded list
                // rather than a hash of its name: hashing collided on two of this hotel's
                // eight types, which defeats the point of colour-coding them at all.
                cls += ' rt-' + type_hue(room.room_type, self.state.room_types);
                var currency = frappe.boot.sysdefaults.currency || 'INR';

                // Capacity and bed layout: what the guest is actually buying.
                var meta = '';
                if(room.max_occupancy){
                    meta += '<span class="rm-cap" title="'+__('Maximum guests allowed')+'">'+
                            '\uD83D\uDC64 '+__('Max {0}', [room.max_occupancy])+'</span>';
                }
                if(room.bedroom_configuration){
                    meta += '<span class="rm-bed">'+frappe.utils.escape_html(room.bedroom_configuration)+'</span>';
                }

                var amen = (room.amenities || []).map(function(a){
                    return '<i title="'+frappe.utils.escape_html(a.label)+'">'+a.icon+'</i>';
                }).join('');

                // Weekend nights cost more, so the flat nightly figure alone would
                // understate the stay. Show both when they disagree.
                var stay = '';
                if(room.stay_total && self.state.nights){
                    var flat = room.rate * self.state.nights;
                    if(Math.abs(room.stay_total - flat) > 0.5){
                        stay = '<span class="rm-stay">'+__('Stay')+': '+
                               format_currency(room.stay_total,currency)+'</span>';
                    }
                }
                var wknd = room.has_weekend_premium
                    ? '<span class="rm-wknd" title="'+__('Charged on Friday, Saturday, Sunday and holiday nights')+'">'+
                      __('Weekend/Holiday')+' '+format_currency(room.weekend_rate,currency)+'</span>'
                    : '';

                // Who is in the room, or booked into it, for these dates.
                var who = '';
                var o = room.occupant;
                if(o){
                    var flag = room.status==='Occupied'
                        ? '<span class="rm-flag in">'+__('In house')+'</span>'
                        : '<span class="rm-flag rs">'+(o.arrives_today ? __('Arriving') : __('Reserved'))+'</span>';
                    who = '<div class="rm-who">'+flag+frappe.utils.escape_html(o.guest_name || '')+'</div>'+
                          '<div class="rm-when">'+frappe.datetime.str_to_user(o.arrival_date)+' → '+
                          frappe.datetime.str_to_user(o.departure_date)+'</div>';
                }

                var $card = $('<div class="'+cls+'" title="'+(o ? frappe.utils.escape_html(o.status+' — '+(o.guest_name||'')) : '')+'">'+
                    '<div class="rm-num">'+frappe.utils.escape_html(room.name)+'</div>'+
                    '<div class="rm-type">'+frappe.utils.escape_html(room.room_type)+'</div>'+
                    who+
                    (meta ? '<div class="rm-meta">'+meta+'</div>' : '')+
                    '<div class="rm-rate">'+format_currency(room.rate,currency)+' <span>/night</span>'+wknd+stay+'</div>'+
                    (amen ? '<div class="rm-amen">'+amen+'</div>' : '')+
                    '<div class="rm-dot '+dot+'"></div>'+
                '</div>');
                if(room.status==='Available'){
                    $card.on('click', function(){ self.toggle(room); });
                } else if(room.occupant){
                    // A booked or occupied room opens that guest on the Guests tab,
                    // where every action for the stay lives.
                    $card.on('click', function(){
                        var o = room.occupant;
                        self.open_stay(o.reservation ? 'reservation' : 'booking', o.reservation || o.booking);
                    });
                }
                $grid.append($card);
            });
        },

        // ---- Guests board ------------------------------------------------
        // Every stay in one list; picking one shows its money and every action.
        load_stays: function(){
            var self = this;
            var view = self.state.stay_view || 'live';
            frappe.call({
                method:'hospitality_core.hospitality_core.api.front_desk.get_stays',
                args:{ view: view, search: $('#pos-stay-q').val() || '' },
                callback: function(r){ if(r.message){ self.render_stays(r.message); } }
            });
        },

        render_stays: function(data){
            var self = this;
            var view = self.state.stay_view || 'live';
            var chips = [
                ['live', __('Today')], ['arriving', __('Arriving')], ['inhouse', __('In house')],
                ['dueout', __('Due out / pending')], ['upcoming', __('Upcoming')], ['holds', __('Holds')],
                ['noshow', __('No show')], ['all', __('All')]
            ];
            $('#pos-stay-chips').html(chips.map(function(c){
                var n = (data.counts || {})[c[0]] || 0;
                return '<button class="st-chip'+(c[0]===view?' active':'')+'" data-view="'+c[0]+'">'+c[1]+'<b>'+n+'</b></button>';
            }).join(''));
            $('#pos-stay-count').text((data.counts || {}).live ? '('+data.counts.live+')' : '');

            var cls = { 'In house':'s-in', 'Due out':'s-in', 'Check-out pending':'s-in', 'Arriving':'s-arr',
                        'Late arrival':'s-arr', 'Upcoming':'s-up', 'Hold':'s-up' };
            var tag = { 'Due out':'g-due', 'Check-out pending':'g-over', 'In house':'g-in', 'Arriving':'g-arr',
                        'Late arrival':'g-late', 'Hold':'g-hold' };
            var rows = data.rows || [];
            if(!rows.length){
                $('#pos-stay-list').html('<div class="cart-empty"><div class="icon">🛏</div>'+__('No guests here')+'</div>');
                return;
            }
            $('#pos-stay-list').html(rows.map(function(o){
                var key = o.kind+':'+o.name;
                var due = flt(o.due);
                return '<div class="st-row '+(cls[o.stage]||'')+(self.state.stay_key===key?' active':'')+'" data-kind="'+o.kind+'" data-name="'+
                        frappe.utils.escape_html(o.name)+'">'+
                    '<div style="min-width:0"><div class="st-name">'+frappe.utils.escape_html(o.guest_name || o.name)+'</div>'+
                    '<div class="st-meta">'+frappe.utils.escape_html(o.room || '')+(o.room_type ? ' · '+frappe.utils.escape_html(o.room_type) : '')+
                        (o.company ? ' · '+frappe.utils.escape_html(o.company) : '')+'</div>'+
                    '<div class="st-meta">'+frappe.datetime.str_to_user(o.arrival_date)+' → '+frappe.datetime.str_to_user(o.departure_date)+
                        ' · '+o.nights+' '+__('night(s)')+(o.mobile_no ? ' · '+frappe.utils.escape_html(o.mobile_no) : '')+'</div></div>'+
                    '<div class="st-side"><span class="st-stage '+(tag[o.stage]||'')+'">'+__(o.stage)+'</span>'+
                    '<span class="st-due'+(due>0.01?'':' zero')+'">'+(due>0.01 ? __('Due')+' '+format_currency(due) : (due < -0.01 ? __('Credit')+' '+format_currency(-due) : __('Settled')))+'</span></div>'+
                '</div>';
            }).join(''));
            $('#pos-stay-list .st-row').on('click', function(){
                self.open_stay($(this).data('kind'), $(this).data('name'));
            });
        },

        open_stay: function(kind, name){
            var self = this;
            if(self.state.mode !== 'stays'){ self.set_mode('stays'); }
            self.state.stay_key = kind+':'+name;
            $('#pos-stay-list .st-row').removeClass('active');
            $('#pos-stay-list .st-row[data-name="'+name+'"]').addClass('active');
            $('#pos-stay-detail').html('<div class="cart-empty"><div class="icon">⏳</div>'+__('Loading...')+'</div>');
            var refresh = function(){ self.open_stay(kind, name); self.load_stays(); };
            if(kind === 'booking'){
                frappe.call({
                    method:'hospitality_core.hospitality_core.page.hotel_crm.hotel_crm.get_booking',
                    args:{ booking: name },
                    callback: function(r){ if(r.message){ self.render_booking_detail(r.message, refresh); } }
                });
            } else {
                frappe.call({
                    method:'hospitality_core.hospitality_core.api.front_desk.get_stay_summary',
                    args:{ reservation: name },
                    callback: function(r){ if(r.message){ self.render_stay_detail(r.message, refresh); } }
                });
            }
        },

        _detail_shell: function(title, sub, stage, body, primary, actions){
            var html = '<div class="cart-hdr"><div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">'+
                    '<div style="min-width:0"><h3>'+frappe.utils.escape_html(title)+'</h3><div class="nights">'+sub+'</div></div>'+
                    '<span class="st-stage">'+frappe.utils.escape_html(stage)+'</span></div></div>'+
                '<div class="cart-body">'+body+'<div class="sd-actions" id="sd-actions"></div><div id="sd-lines"></div></div>'+
                '<div class="cart-footer" id="sd-primary"></div>';
            $('#pos-stay-detail').html(html);
            if(primary){
                var $p = $('<button class="btn-book">'+primary.label+'</button>').on('click', primary.fn);
                $('#sd-primary').append($p);
            } else {
                $('#sd-primary').remove();
            }
            actions.forEach(function(a){
                if(!a) return;
                $('#sd-actions').append($('<button'+(a.danger?' class="danger"':'')+'>'+a.label+'</button>').on('click', a.fn));
            });
        },

        render_stay_detail: function(s, refresh){
            var stay = frappe.hospitality.stay;
            var g = s.guest_detail || {};
            var f = s.folio || {};
            var fmt = function(v){ return format_currency(flt(v)); };
            var today = frappe.datetime.now_date();
            var in_house = s.status === 'Checked In';
            var reserved = s.status === 'Reserved' || s.status === 'No Show';
            var credit = -flt(s.balance) > 0.01 && !flt(s.unapplied_advance) ? -flt(s.balance) : 0;

            var money;
            if(reserved){
                var b = s.booking || {};
                money = '<div><span>'+__('Stay total (estimate)')+'</span><span>'+fmt(s.stay_estimate_total)+'</span></div>'+
                    '<div class="ok"><span>'+__('Advance paid')+'</span><span>'+fmt(s.unapplied_advance)+'</span></div>'+
                    '<div class="big"><span>'+__('To pay')+'</span><span>'+fmt(Math.max(s.stay_estimate_total - flt(s.unapplied_advance), 0))+'</span></div>';
            } else {
                money = '<div><span>'+__('Charges')+'</span><span>'+fmt(f.total_charges)+'</span></div>'+
                    (flt(f.total_discounts) ? '<div class="ok"><span>'+__('Discounts')+'</span><span>−'+fmt(f.total_discounts)+'</span></div>' : '')+
                    '<div class="ok"><span>'+__('Paid')+'</span><span>−'+fmt(f.total_payments)+'</span></div>'+
                    (flt(s.unapplied_advance) ? '<div class="ok"><span>'+__('Advance waiting')+'</span><span>−'+fmt(s.unapplied_advance)+'</span></div>' : '')+
                    '<div class="big"><span>'+(credit ? __('Credit') : __('Balance'))+'</span><span>'+fmt(credit || s.to_collect)+'</span></div>'+
                    (in_house && s.pending_total ? '<div><span>'+__('Nights still to post')+'</span><span>'+fmt(s.pending_total)+'</span></div>' : '');
            }
            var body = '<div class="arr-meta" style="white-space:normal">'+
                    frappe.utils.escape_html(g.mobile_no || '')+(s.company ? ' · '+__('Billed to {0}', [frappe.utils.escape_html(s.company)]) : '')+'</div>'+
                '<div style="margin-top:6px;font-weight:600">'+frappe.utils.escape_html(s.room)+' · '+frappe.utils.escape_html(s.room_type || '')+'</div>'+
                '<div class="arr-meta">'+frappe.datetime.str_to_user(s.arrival_date)+' → '+frappe.datetime.str_to_user(s.departure_date)+
                    ' · '+s.nights+' '+__('night(s)')+' · '+cint(s.adults)+' '+__('adult(s)')+(cint(s.children) ? ', '+cint(s.children)+' '+__('child(ren)') : '')+'</div>'+
                '<div class="sd-money">'+money+'</div>';

            var primary = null;
            if(s.status === 'Checked In'){
                primary = { label: __('Check Out'), fn: function(){ stay.check_out(s.reservation, {on_done: refresh}); } };
            } else if(reserved && s.arrival_date <= today){
                primary = { label: __('Check In'), fn: function(){
                    if(s.status === 'No Show'){
                        frappe.call({ method:'hospitality_core.hospitality_core.page.hotel_pos.hotel_pos.checkin_arrival',
                            args: s.booking && s.booking.name ? { booking: s.booking.name } : { reservation: s.reservation },
                            freeze:true }).then(function(){ frappe.show_alert({message:__('Checked in'), indicator:'green'}); refresh(); });
                    } else {
                        stay.check_in(s.reservation, {on_done: refresh});
                    }
                } };
            }

            var due = in_house ? s.to_collect : Math.max(s.stay_estimate_total - flt(s.unapplied_advance), 0);
            var actions = [
                (in_house || reserved) ? { label: __('Take Payment'), fn: function(){ stay.take_payment(s.reservation, {due: due, on_done: refresh}); } } : null,
                (in_house || reserved) ? { label: in_house ? __('Extend / Dates') : __('Change Dates'), fn: function(){ stay.change_dates(s.reservation, {extend: in_house, on_done: refresh}); } } : null,
                in_house ? { label: __('Add Charge'), fn: function(){ stay.add_charge(s.reservation, {on_done: refresh}); } } : null,
                (in_house || s.status === 'Reserved') ? { label: __('Move Room'), fn: function(){ stay.move_room(s.reservation, {on_done: refresh}); } } : null,
                f.name ? { label: __('Print Bill'), fn: function(){ stay.print_bill(f.name); } } : null,
                credit ? { label: __('Refund {0}', [fmt(credit)]), fn: function(){ stay.refund(s.reservation, {credit: credit, on_done: refresh}); } } : null,
                (s.invoices || []).length ? { label: __('Invoice'), fn: function(){ frappe.set_route('Form', 'Sales Invoice', s.invoices[0].name); } } : null,
                { label: __('Open Reservation'), fn: function(){ frappe.set_route('Form', 'Hotel Reservation', s.reservation); } },
                (s.booking && s.booking.name) ? { label: __('Open Booking'), fn: function(){ frappe.set_route('Form', 'Hotel Booking', s.booking.name); } } : null,
                reserved ? { label: __('Cancel Stay'), danger: true, fn: function(){ stay.cancel(s.reservation, {on_done: refresh}); } } : null,
            ];
            this._detail_shell(g.full_name || s.guest, frappe.utils.escape_html(s.reservation), __(s.status), body, primary, actions);

            var lines = (s.lines || []).slice(-8);
            if(lines.length){
                $('#sd-lines').html('<div class="cart-sec" style="margin-top:12px">'+__('Latest on the bill')+'</div><div class="sd-lines">'+
                    lines.map(function(l){
                        var cr = l.kind !== 'charge';
                        return '<div><span>'+frappe.datetime.str_to_user(l.posting_date)+' · '+frappe.utils.escape_html(l.description || l.item)+'</span>'+
                            '<span class="'+(cr?'cr':'')+'">'+(cr ? '−'+fmt(Math.abs(l.amount)) : fmt(l.amount))+'</span></div>';
                    }).join('')+'</div>');
            }
        },

        render_booking_detail: function(b, refresh){
            var stay = frappe.hospitality.stay;
            var fmt = function(v){ return format_currency(flt(v)); };
            var M = 'hospitality_core.hospitality_core.doctype.hotel_booking.hotel_booking.';
            var rooms = (b.rooms || []).map(function(l){
                return frappe.utils.escape_html(l.room || l.room_type)+(l.room ? '' : ' ('+__('any')+')');
            }).join(', ');
            var body = '<div class="arr-meta">'+frappe.utils.escape_html(b.mobile_no || '')+'</div>'+
                '<div style="margin-top:6px;font-weight:600">'+rooms+'</div>'+
                '<div class="arr-meta">'+frappe.datetime.str_to_user(b.arrival_date)+' → '+frappe.datetime.str_to_user(b.departure_date)+
                    ' · '+b.nights+' '+__('night(s)')+(b.hold_expiry ? ' · '+__('hold until {0}', [frappe.datetime.str_to_user(b.hold_expiry)]) : '')+'</div>'+
                '<div class="sd-money"><div><span>'+__('Total')+'</span><span>'+fmt(b.total_amount)+'</span></div>'+
                    '<div class="ok"><span>'+__('Advance')+'</span><span>−'+fmt(b.advance_received)+'</span></div>'+
                    '<div class="big"><span>'+__('Balance due')+'</span><span>'+fmt(b.balance_due)+'</span></div></div>';
            var arrived = b.arrival_date <= frappe.datetime.now_date();
            var primary = arrived
                ? { label: __('Confirm & Check In'), fn: function(){
                        frappe.call({ method:'hospitality_core.hospitality_core.page.hotel_pos.hotel_pos.checkin_arrival',
                            args:{ booking: b.name }, freeze:true }).then(function(r){
                                if(r.message){ frappe.show_alert({message:__('Checked in'), indicator:'green'}); refresh(); } });
                    } }
                : { label: __('Confirm Booking'), fn: function(){
                        frappe.call({ method: M+'confirm_booking', args:{ booking: b.name }, freeze:true }).then(function(){
                            frappe.show_alert({message:__('Booking confirmed'), indicator:'green'}); refresh(); });
                    } };
            var actions = [
                { label: __('Take Advance'), fn: function(){ stay.take_payment({booking: b.name}, {due: b.balance_due, on_done: refresh}); } },
                { label: __('Change Dates'), fn: function(){ stay.change_booking_dates(b.name, {on_done: refresh}); } },
                { label: __('Open Booking'), fn: function(){ frappe.set_route('Form', 'Hotel Booking', b.name); } },
                { label: __('Cancel Hold'), danger: true, fn: function(){
                    frappe.prompt({ fieldtype:'Small Text', fieldname:'reason', label:__('Reason'), reqd:1 }, function(v){
                        frappe.call({ method: M+'cancel_booking', args:{ booking: b.name, reason: v.reason }, freeze:true })
                            .then(function(){ frappe.show_alert({message:__('Hold released'), indicator:'orange'}); refresh(); });
                    }, __('Cancel Hold'), __('Cancel Hold'));
                } },
            ];
            this._detail_shell(b.guest_name || b.guest, frappe.utils.escape_html(b.name), __(b.status), body, primary, actions);
        },

        // A booked or occupied card opens what the desk can do with that guest.
        room_actions: function(room){
            var self = this;
            var o = room.occupant || {};
            var stay = frappe.hospitality.stay;
            var reload = function(){ self.load(); };
            var html = '<div class="hfd-head"><div><div class="hfd-guest">'+frappe.utils.escape_html(o.guest_name || '')+'</div>'+
                '<div class="hfd-sub">'+frappe.utils.escape_html(o.mobile_no || '')+'</div></div>'+
                '<div class="hfd-room"><div class="hfd-room-no">'+frappe.utils.escape_html(room.name)+'</div>'+
                '<div class="hfd-sub">'+frappe.utils.escape_html(room.room_type)+'</div></div></div>'+
                '<div class="hfd-stay"><span>'+frappe.datetime.str_to_user(o.arrival_date)+' → '+
                frappe.datetime.str_to_user(o.departure_date)+'</span><span>'+frappe.utils.escape_html(o.status || '')+'</span>'+
                (o.booking ? '<span>'+frappe.utils.escape_html(o.booking)+'</span>' : '')+'</div>';

            var d = new frappe.ui.Dialog({ title: room.name, fields: [{fieldtype:'HTML', options: html}] });
            var add = function(label, fn, primary){
                var $b = $('<button class="btn btn-sm '+(primary?'btn-primary':'btn-default')+'" style="margin:4px 6px 0 0">'+label+'</button>');
                $b.on('click', function(){ d.hide(); fn(); });
                d.$body.append($b);
            };
            if(o.status === 'Checked In' && o.reservation){
                add(__('Check Out'), function(){ stay.check_out(o.reservation, {on_done: reload}); }, true);
                add(__('Extend Stay'), function(){ stay.extend(o.reservation, {on_done: reload}); });
            } else if(o.status === 'Reserved' && o.reservation && o.arrives_today){
                add(__('Check In'), function(){ stay.check_in(o.reservation, {on_done: reload}); }, true);
            } else if(o.booking && o.arrives_today){
                // A hold on a Tentative booking: confirming and checking in happen together.
                add(__('Check In'), function(){
                    frappe.call({
                        method:'hospitality_core.hospitality_core.page.hotel_pos.hotel_pos.checkin_arrival',
                        args:{ booking: o.booking }, freeze:true
                    }).then(function(r){ if(r.message){ frappe.show_alert({message:__('Checked in'), indicator:'green'}); reload(); } });
                }, true);
            }
            if(o.booking){ add(__('Open Booking'), function(){ frappe.set_route('Form','Hotel Booking', o.booking); }); }
            if(o.reservation){ add(__('Open Reservation'), function(){ frappe.set_route('Form','Hotel Reservation', o.reservation); }); }
            d.show();
        },

        toggle: function(room){
            var idx = -1;
            for(var i=0;i<this.state.cart.length;i++){
                if(this.state.cart[i].name===room.name){idx=i;break;}
            }
            if(idx>-1) this.state.cart.splice(idx,1);
            else this.state.cart.push(room);
            this.render_grid();
            this.render_cart();
            this.render_stats();
        },

        render_cart: function(){
            var self = this;
            var $list = $('#cart-list');
            $list.empty();
            var total = 0;
            var currency = frappe.boot.sysdefaults.currency || 'INR';
            if(!self.state.cart.length){
                $list.html('<div class="cart-empty"><div class="icon">🛒</div>Select rooms from the left panel</div>');
            } else {
                var has_weekend = false;
                var capacity = 0;
                var override = flt(self.state.rate_override);
                self.state.cart.forEach(function(room){
                    // stay_total is priced night by night on the server, so a stay
                    // spanning a weekend is charged correctly instead of rate x nights.
                    // An agreed rate replaces the tariff for every night.
                    var rt = override
                        ? override * self.state.nights
                        : (room.stay_total || (room.rate * self.state.nights));
                    total += rt;
                    capacity += (room.max_occupancy || 0);

                    var sub = frappe.utils.escape_html(room.room_type);
                    if(override){
                        sub += ' &middot; '+format_currency(override,currency)+' '+__('agreed')+
                               ' &times; '+self.state.nights+' '+__('nights');
                    } else if(room.stay_total && Math.abs(room.stay_total - room.rate*self.state.nights) > 0.5){
                        has_weekend = true;
                        sub += ' &middot; '+format_currency(room.average_nightly,currency)+
                               ' '+__('avg')+' &times; '+self.state.nights+' '+__('nights');
                    } else {
                        sub += ' &middot; '+format_currency(room.rate,currency)+
                               ' &times; '+self.state.nights+' '+__('nights');
                    }

                    var amen = (room.amenities || []).map(function(a){ return a.icon; }).join(' ');
                    var cap = room.max_occupancy
                        ? '<div class="ci-amen">\uD83D\uDC64 '+__('Max {0}', [room.max_occupancy])+
                          (amen ? ' &nbsp; '+amen : '')+'</div>'
                        : (amen ? '<div class="ci-amen">'+amen+'</div>' : '');

                    $list.append(
                        '<div class="cart-item">'+
                          '<div><div class="ci-name">'+frappe.utils.escape_html(room.name)+'</div>'+
                          '<div class="ci-sub">'+sub+'</div>'+cap+'</div>'+
                          '<div style="display:flex;align-items:center">'+
                            '<div class="ci-price">'+format_currency(rt,currency)+'</div>'+
                            '<button class="ci-rm" data-room="'+frappe.utils.escape_html(room.name)+'">&times;</button>'+
                          '</div>'+
                        '</div>'
                    );
                });

                // Over capacity is sold with extra beds rather than refused, so show
                // what that adds instead of warning the desk off the sale.
                var guests = cint(self.state.adults) + cint(self.state.children);
                if(guests && capacity && guests > capacity){
                    var over = guests - capacity;
                    var bed_cost = self.state.cart.reduce(function(acc, r){
                        return Math.max(acc, flt(r.extra_bed_adult_rate));
                    }, 0) * over * self.state.nights;
                    $list.append('<div class="ci-info">\uD83D\uDECF '+
                        __('{0} guest(s) over capacity — {1} extra bed(s) will be added, about {2}.',
                           [over, over, format_currency(bed_cost, currency)])+'</div>');
                    total += bed_cost;
                }
                if(has_weekend && !override){
                    $list.append('<div class="cart-note">'+
                        __('Totals include the weekend tariff for Friday, Saturday, Sunday and holiday nights.')+
                        '</div>');
                }
                if(override){
                    $list.append('<div class="cart-note">'+
                        __('An agreed rate of {0} replaces the tariff for every night.',
                           [format_currency(override, currency)])+'</div>');
                }

                // The discount comes off the gross, exactly as the folio will post it.
                var dtype = self.state.discount_type;
                var dvalue = flt(self.state.discount_value);
                if(dtype && dvalue > 0){
                    var disc = dtype === 'Percentage'
                        ? total * (Math.min(dvalue, 100) / 100)
                        : Math.min(dvalue, total);
                    disc = Math.max(Math.min(disc, total), 0);
                    total -= disc;
                    $list.append('<div class="cart-note">'+
                        __('Discount applied: {0}', [format_currency(disc, currency)])+'</div>');
                }
                $list.off('click','.ci-rm').on('click','.ci-rm',function(){
                    var rn = $(this).data('room');
                    var rm = self.state.rooms.find(function(r){return r.name===rn});
                    if(rm) self.toggle(rm);
                });
            }
            // Selling past rooms of a type already promised on bookings oversells it.
            var picked = {};
            self.state.cart.forEach(function(r){ picked[r.room_type] = (picked[r.room_type]||0) + 1; });
            Object.keys(picked).forEach(function(t){
                var held = (self.state.held || {})[t] || 0;
                if(!held) return;
                var free = self.state.rooms.filter(function(r){ return r.room_type===t && r.status==='Available'; }).length;
                if(picked[t] > free - held){
                    $list.append('<div class="ci-warn">'+__('{0}: {1} room(s) of this type are promised on bookings without a room number. Selling this leaves them short.', [frappe.utils.escape_html(t), held])+'</div>');
                }
            });

            $('#cart-total-val').text(format_currency(total, currency));
            self.state.cart_total = total;
            var arriving_today = self.state.arrival === frappe.datetime.now_date();
            $('#pos-checkin-wrap').toggle(arriving_today);
            if(!arriving_today){ $('#pos-checkin-now').prop('checked', false); }
            self.refresh_btn();
        },

        refresh_btn: function(){
            var ok = this.state.cart.length > 0;
            if(this.state.is_new_guest){
                if(!$('#gf-name').val() || !$('#gf-name').val().trim()) ok = false;
            } else {
                if(!this.state.selected_guest) ok = false;
            }
            $('#btn-confirm').prop('disabled',!ok)
                .text($('#pos-checkin-now').is(':checked') ? __('Book & Check In') : __('Confirm Booking'));
        },

        reset_cart: function(){
            this.state.cart = [];
            $('#pos-advance, #pos-ref, #pos-remarks, #pos-rate-override').val('');
            $('#pos-discount-type').val(''); $('#pos-discount-value').val(0);
            $('#pos-checkin-now').prop('checked', false);
            $('#new-guest-form input').val('');
            this.render_cart();
        },

        book: function(){
            var self = this;
            
            if(self.state.is_new_guest){
                var aadhaar = $('#gf-aadhaar').val().replace(/\s/g, '');
                if (aadhaar && aadhaar.length !== 12) {
                    frappe.msgprint("Aadhaar Number must be exactly 12 digits.");
                    return;
                }
                var pan = $('#gf-pan').val().replace(/\s/g, '');
                if (pan && pan.length !== 10) {
                    frappe.msgprint("PAN Number must be exactly 10 characters.");
                    return;
                }
            }
            
            $('#btn-confirm').prop('disabled',true).text('Processing...');
            var payload = {
                arrival: self.state.arrival,
                departure: self.state.departure,
                arrival_time: self.state.arrival_time || '',
                departure_time: self.state.departure_time || '',
                adults: $('#pos-adults').val() || 1,
                children: $('#pos-children').val() || 0,
                rate_override: flt($('#pos-rate-override').val()),
                discount_type: $('#pos-discount-type').val() || '',
                discount_value: flt($('#pos-discount-value').val()),
                remarks: $('#pos-remarks').val() || '',
                rooms: self.state.cart.map(function(c){return c.name}),
                is_new_guest: self.state.is_new_guest,
                advance_amount: flt($('#pos-advance').val()),
                mode_of_payment: $('#pos-mop').val() || 'Cash',
                reference_no: $('#pos-ref').val() || '',
                check_in_now: $('#pos-checkin-now').is(':checked') ? 1 : 0
            };
            if(self.state.is_new_guest){
                payload.guest_details = {
                    full_name: $('#gf-name').val(),
                    phone: $('#gf-phone').val(),
                    email: $('#gf-email').val(),
                    nationality: $('#gf-nationality').val(),
                    aadhaar: aadhaar,
                    pan: pan,
                    guest_type: $('#gf-type').val(),
                    gender: $('#gf-gender').val(),
                    address: $('#gf-address').val(),
                    special_requests: $('#gf-requests').val()
                };
            } else {
                payload.guest = self.state.selected_guest;
            }
            frappe.call({
                method:'hospitality_core.hospitality_core.page.hotel_pos.hotel_pos.submit_pos_booking',
                args:{ payload: JSON.stringify(payload) },
                callback: function(r){
                    if(!r.exc && r.message && r.message.success){
                        var m = r.message;
                        if((m.checked_in || []).length){
                            // Walk-in: they are in the room now. Stay on the POS, ready
                            // for the next guest, with the grid showing the room In House.
                            frappe.show_alert({message: __('{0} checked in · booking {1}', [m.checked_in.length+' '+__('room(s)'), m.booking]), indicator:'green'}, 7);
                            self.reset_cart();
                            self.load();
                        } else {
                            frappe.show_alert({message: __('Booking {0} confirmed', [m.booking]), indicator:'green'}, 5);
                            frappe.set_route('Form','Hotel Booking', m.booking);
                        }
                    } else {
                        self.refresh_btn();
                    }
                },
                error: function(){ self.refresh_btn(); }
            });
        }
    };

    window.pos_app = POS;
    POS.init();
    POS.apply_route_options = function(){
        var o = frappe.route_options || {};
        frappe.route_options = null;
        if(o.reservation){ POS.open_stay('reservation', o.reservation); }
        else if(o.booking){ POS.open_stay('booking', o.booking); }
        else if(o.mode){ POS.set_mode(o.mode); }
    };
    POS.apply_route_options();
};

frappe.pages['hotel-pos'].on_page_show = function(){
    if(window.pos_app && window.pos_app.apply_route_options && frappe.route_options){
        window.pos_app.apply_route_options();
    }
};

/* ---------------------------------------------------------------- dd/mm/yy dates
 * A native <input type="date"> shows whatever format the computer's locale uses
 * (mm/dd/yyyy on many). These fields show dd/mm/yy instead, with Frappe's own date
 * picker, and keep the real value as YYYY-MM-DD in data-iso for the server. */
function pos_iso(d){
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}
function pos_fmt(iso){
    if(!iso) return '';
    var p = iso.split('-');
    return p[2] + '/' + p[1] + '/' + p[0].slice(2);
}
/* Typed text: dd/mm/yy, dd/mm/yyyy, dd-mm-yy or dd.mm.yyyy. Null if not a real date. */
function pos_parse(text){
    var m = String(text || '').trim().match(/^(\d{1,2})[\/.\-](\d{1,2})[\/.\-](\d{2}|\d{4})$/);
    if(!m) return null;
    var y = m[3].length === 2 ? 2000 + parseInt(m[3], 10) : parseInt(m[3], 10);
    var d = new Date(y, parseInt(m[2], 10) - 1, parseInt(m[1], 10));
    if(d.getDate() !== parseInt(m[1], 10) || d.getMonth() !== parseInt(m[2], 10) - 1) return null;
    return pos_iso(d);
}
function pos_date_val(sel){
    return $(sel).attr('data-iso') || '';
}
function set_pos_date(sel, iso){
    var $el = $(sel);
    $el.attr('data-iso', iso).val(pos_fmt(iso));
    var dp = $el.data('datepicker');
    if(dp){ dp.selectDate(new Date(iso + 'T00:00:00'), { silent: true }); }
}
function init_pos_date(sel, on_change){
    var $el = $(sel);
    var commit = function(iso){
        if(!iso) { $el.val(pos_fmt(pos_date_val(sel))); return; }   // not a date: put the last good one back
        var changed = iso !== pos_date_val(sel);
        $el.attr('data-iso', iso).val(pos_fmt(iso));
        if(changed && on_change) on_change(iso);
    };
    $el.val(pos_fmt(pos_date_val(sel)));
    if($.fn.datepicker){
        var lang = (frappe.boot.user && frappe.boot.user.language) || 'en';
        if(!$.fn.datepicker.language[lang]) lang = 'en';
        $el.datepicker({
            language: lang,
            autoClose: true,
            todayButton: new Date(),
            keyboardNav: false,
            dateFormat: 'dd/mm/yy',
            firstDay: frappe.datetime.get_first_day_of_the_week_index ? frappe.datetime.get_first_day_of_the_week_index() : 1,
            onSelect: function(_fd, date){ if(date) commit(pos_iso(date)); }
        });
        var dp = $el.data('datepicker');
        if(dp && pos_date_val(sel)){ dp.selectDate(new Date(pos_date_val(sel) + 'T00:00:00')); }
    }
    $el.on('change blur', function(){
        var typed = pos_parse($el.val());
        if(typed){ if(typed !== pos_date_val(sel)) commit(typed); }
        else { $el.val(pos_fmt(pos_date_val(sel))); }
    });
}

var RT_HUES = 8;

function type_hue(name, types){
    var i = -1;
    (types || []).some(function(t, idx){
        if((t && t.name ? t.name : t) === name){ i = idx; return true; }
        return false;
    });
    if(i > -1) return i % RT_HUES;

    // Not in the list (a room whose type was filtered out, or removed): fall back to a
    // hash so it still gets a stable colour rather than an unstyled edge.
    var h = 0, str = String(name || '');
    for(var c = 0; c < str.length; c++){ h = (h * 31 + str.charCodeAt(c)) >>> 0; }
    return h % RT_HUES;
}

function build_layout(){
    var today = frappe.datetime.now_date();
    var tomorrow = frappe.datetime.add_days(today, 1);
    return '<div class="hpos">'+
      '<div class="hpos-left">'+
        '<div class="hpos-topbar">'+
          '<div class="logo-icon"><img src="/files/logo.jpeg" alt=""></div>'+
          '<div><h2>Hotel POS</h2><p class="subtitle">Quick Reservation &amp; Guest Registration</p></div>'+
          '<div class="hpos-modes">'+
            '<button class="hpos-mode active" data-mode="new">New Booking</button>'+
            '<button class="hpos-mode" data-mode="stays">'+__('Guests')+' <span id="pos-stay-count"></span></button>'+
            '<button class="hpos-mode" data-mode="arrivals">Group Arrivals <span id="pos-arr-count"></span></button>'+
          '</div>'+
        '</div>'+
        '<div class="hpos-filters">'+
          '<div class="hpos-fg"><label>Check-in</label><input type="text" class="pos-date" id="pos-arr" data-iso="'+today+'" autocomplete="off" placeholder="dd/mm/yy" style="width:110px"></div>'+

          '<div class="hpos-fg"><label>Check-out</label><input type="text" class="pos-date" id="pos-dep" data-iso="'+tomorrow+'" autocomplete="off" placeholder="dd/mm/yy" style="width:110px"></div>'+
          '<div class="hpos-fg"><label>'+__('Times')+'</label><div id="pos-stay-times" style="height:30px;line-height:30px;font-size:var(--text-sm,12px);color:var(--dim);white-space:nowrap"></div></div>'+
          '<div class="hpos-fg"><label>Adults</label><input type="number" id="pos-adults" value="1" min="1" max="30" style="width:70px"></div>'+
          '<div class="hpos-fg"><label>Children</label><input type="number" id="pos-children" value="0" min="0" max="30" style="width:70px"></div>'+
          '<button class="hpos-btn hpos-btn-primary" id="pos-search-btn">Check Availability</button>'+
        '</div>'+
        '<div class="hpos-stats">'+
          '<div class="hpos-stat stat-green"><div class="num" id="stat-avail">-</div><div class="lbl">Available</div></div>'+
          '<div class="hpos-stat stat-amber"><div class="num" id="stat-rsv">-</div><div class="lbl">Reserved</div></div>'+
          '<div class="hpos-stat stat-red"><div class="num" id="stat-occ">-</div><div class="lbl">In House</div></div>'+
          '<div class="hpos-stat stat-blue"><div class="num" id="stat-pct">-</div><div class="lbl">Occupancy</div></div>'+
          '<div class="hpos-stat"><div class="num" id="stat-sel">0</div><div class="lbl">Selected</div></div>'+
        '</div>'+
        '<div class="hpos-type-tabs" id="pos-type-tabs"></div>'+
        '<div class="hpos-grid" id="pos-grid"></div>'+
        '<div class="hpos-arrivals" id="pos-arrivals" style="display:none">'+
          '<div class="hpos-arr-search">'+
            '<input type="text" class="pos-date" id="pos-arr-date" data-iso="'+today+'" autocomplete="off" placeholder="dd/mm/yy">'+
            '<input type="search" id="pos-arr-q" placeholder="Search name, phone or booking no">'+
            '<button class="hpos-btn hpos-btn-primary" id="pos-arr-refresh">Find</button>'+
          '</div>'+
          '<div id="pos-arr-list"></div>'+
        '</div>'+
        '<div class="hpos-stays" id="pos-stays" style="display:none">'+
          '<div class="st-bar"><input type="search" id="pos-stay-q" placeholder="'+__('Search guest, phone, room or booking')+'"></div>'+
          '<div class="st-chips" id="pos-stay-chips"></div>'+
          '<div id="pos-stay-list"></div>'+
        '</div>'+
      '</div>'+
      '<div class="hpos-right">'+
        '<div id="pos-arr-detail" class="pane-hidden"></div>'+
        '<div id="pos-stay-detail" class="pane-hidden"><div class="cart-empty"><div class="icon">👤</div>'+__('Pick a guest to see their bill and actions')+'</div></div>'+
        '<div id="pos-cart-pane">'+
        '<div class="cart-hdr"><h3>Booking Summary</h3><div class="nights"><span id="cart-nights">1</span> Night(s) Stay</div></div>'+
        '<div class="cart-body">'+
          '<div class="cart-sec">Selected Rooms</div>'+
          '<div id="cart-list"><div class="cart-empty"><div class="icon">🛒</div>Select rooms from the left panel</div></div>'+
          '<div class="cart-sec">Rate &amp; Discount</div>'+
          '<div class="gf-row"><label>Agreed Rate / Night</label>'+
            '<input id="pos-rate-override" type="number" min="0" step="any" placeholder="Tariff rate">'+
          '</div>'+
          '<div class="gf-row"><label>Discount</label>'+
            '<select id="pos-discount-type" style="width:46%">'+
              '<option value="">None</option><option value="Amount">Amount</option>'+
              '<option value="Percentage">Percentage</option>'+
            '</select>'+
            '<input id="pos-discount-value" type="number" min="0" step="any" value="0" style="width:50%">'+
          '</div>'+
          '<div class="gf-row"><label>Remarks</label>'+
            '<input id="pos-remarks" placeholder="Shown on the folio and the bill">'+
          '</div>'+
          '<div class="cart-sec">'+__('Payment now (optional)')+'</div>'+
          '<div class="gf-row"><label>'+__('Advance / Payment')+'</label>'+
            '<input id="pos-advance" type="number" min="0" step="any" placeholder="0" style="width:48%">'+
            '<select id="pos-mop" style="width:48%;margin-left:4%">'+
              '<option>Cash</option>'+
            '</select>'+
          '</div>'+
          '<div class="gf-row"><label>'+__('Reference / UTR')+'</label><input id="pos-ref" placeholder="'+__('Optional')+'"></div>'+
          '<label class="cart-check" id="pos-checkin-wrap"><input type="checkbox" id="pos-checkin-now"> '+
            __('Check the guest in now')+'</label>'+
          '<div class="cart-sec">Guest Details</div>'+
          '<div id="guest-link-wrapper"></div>'+
          '<button class="guest-toggle" id="btn-new-guest">+ New Guest</button>'+
          '<div class="guest-form" id="new-guest-form">'+
            '<div class="gf-row"><label>Full Name *</label><input id="gf-name" placeholder="Enter full name"></div>'+
            '<div class="gf-row"><label>Guest Type</label><select id="gf-type"><option value="Regular">Regular</option><option value="VIP">VIP</option><option value="Corporate">Corporate</option><option value="Staff">Staff</option><option value="Blacklisted">Blacklisted</option></select></div>'+
            '<div class="gf-row"><label>Gender</label><select id="gf-gender"><option value=""></option><option value="Male">Male</option><option value="Female">Female</option><option value="Other">Other</option></select></div>'+
            '<div class="gf-row"><label>Phone</label><input id="gf-phone" placeholder="+91 98765 43210"></div>'+
            '<div class="gf-row"><label>Email</label><input id="gf-email" type="email" placeholder="guest@email.com"></div>'+
            '<div class="gf-row"><label>Address</label><input id="gf-address" placeholder="Address"></div>'+
            '<div class="gf-row"><label>Nationality</label><input id="gf-nationality" value="Indian"></div>'+
            '<div class="gf-row"><label>Aadhaar (Optional)</label><input id="gf-aadhaar" placeholder="1234 5678 9012"></div>'+
            '<div class="gf-row"><label>PAN (Optional)</label><input id="gf-pan" placeholder="ABCDE1234F"></div>'+
            '<div class="gf-row"><label>Special Requests</label><input id="gf-requests" placeholder="Any special requests..."></div>'+
          '</div>'+
        '</div>'+
        '<div class="cart-footer">'+
          '<div class="cart-total"><span>Total</span><span id="cart-total-val">₹0</span></div>'+
          '<button class="btn-book" id="btn-confirm" disabled>Confirm Booking</button>'+
        '</div>'+
        '</div>'+
      '</div>'+
    '</div>';
}