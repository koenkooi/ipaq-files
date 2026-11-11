// SPDX-FileCopyrightText: 2026 Koen Kooi
// SPDX-License-Identifier: GPL-2.0-or-later
//
// Generator for the HP Photosmart Mobile Camera drawings. Usage: node gen-camera.js [output directory]
// Model: x right, y down, z toward the viewer. Every part is projected
// orthographically after a rotation about the horizontal x axis through
// the head's centre (ay): Y = ay + (y-ay)cos(a) - z sin(a).
// The body and plug use a = -PHI (seen from slightly above); the head
// assembly (head block, barrel, focus marks) uses a = theta - PHI.
'use strict';
const fs = require('fs');
const OUT = (process.argv[2] || '.') + '/';
const D2R = Math.PI / 180;
const f = n => (Math.round(n * 100) / 100).toString();

// ---- geometry (units: photo 7 pixels x 0.711, body width 300) ----
const G = {
  bx0: 0, bx1: 300, by0: 60, by1: 323,       // body main block
  footX1: 355, footY0: 284,                   // foot / step under the head
  hx0: 300, hx1: 555, hy0: 53, hy1: 266,      // head front face
  D: 130,                                     // depth of body and head
  lx: 437, ly: 167, R: 92, L: 100,            // lens barrel
  px0: 92, px1: 336, py1: 668, pz: 6,         // plug (SD shaped)
};
G.ay = (G.hy0 + G.hy1) / 2;
const Z = G.D / 2;

function frontT(c, a) { // plane z=c, contents in absolute (x,y)
  const ca = Math.cos(a), sa = Math.sin(a);
  return [G.ay * (1 - ca) - c * sa, ca];
}
function sideT(c, a) { // plane y=c, contents in (x,z)
  const ca = Math.cos(a), sa = Math.sin(a);
  return [G.ay + (c - G.ay) * ca, -sa];
}
const tstr = ([ty, s]) => `translate(0 ${f(ty)}) scale(1 ${f(s)})`;

// ---- animation timeline (10 s) ----
const DUR = 10;
const ease = s => (1 - Math.cos(Math.PI * s)) / 2;
function thetaAt(t) {
  if (t <= 1) return 0;
  if (t <= 5) return 180 * ease((t - 1) / 4);
  if (t <= 6.5) return 180;
  if (t <= 9.5) return 180 * (1 - ease((t - 6.5) / 3));
  return 0;
}
const times = [0];
for (let i = 0; i <= 28; i++) times.push(1 + 4 * i / 28);
for (let i = 0; i <= 21; i++) times.push(6.5 + 3 * i / 21);
times.push(DUR);
const keyTimes = times.map(t => f(t / DUR)).join(';');

// plane group for the head: static (theta given) or animated (theta=null)
// light from above and in front; darkness of a face from its rotated normal
const LY = -0.7, LZ = 0.71;
function shadeRaw(n) { // n = [ny, nz] after rotation
  const d = n[0] * LY + n[1] * LZ;
  return 0.8 * (0.62 - d);
}
// relative to the front face of the body as it is seen (which is not shaded)
function shadeOp(n) {
  const base = shadeRaw([Math.sin(PHI * D2R), Math.cos(PHI * D2R)]);
  return Math.max(0, Math.min(0.3, shadeRaw(n) - Math.max(0, base)));
}
const NORMAL = {
  front: a => [-Math.sin(a), Math.cos(a)], back: a => [Math.sin(a), -Math.cos(a)],
  top: a => [-Math.cos(a), -Math.sin(a)], bottom: a => [Math.cos(a), Math.sin(a)],
};
function headPlane(kind, c, content, theta, vis, shade) {
  const T = kind === 'front' ? frontT : sideT;
  if (theta !== null) {
    const a = (theta - PHI) * D2R;
    if (vis && !vis(a)) return '';
    const ov = shade ? `${shade[0]} fill="#000" opacity="${f(shadeOp(NORMAL[shade[1]](a)))}"/>` : '';
    return `<g transform="${tstr(T(c, a))}">${content}${ov}</g>`;
  }
  const tr = [], sc = [], vv = [], op = [];
  for (const t of times) {
    const a = (thetaAt(t) - PHI) * D2R;
    const [ty, s] = T(c, a);
    tr.push('0 ' + f(ty)); sc.push('1 ' + f(s));
    if (vis) vv.push(vis(a) ? 'visible' : 'hidden');
    if (shade) op.push(f(shadeOp(NORMAL[shade[1]](a))));
  }
  const a0 = -PHI * D2R;
  const [ty0, s0] = T(c, a0);
  const rep = `dur="${DUR}s" repeatCount="indefinite" keyTimes="${keyTimes}"`;
  if (shade) content += `${shade[0]} fill="#000" opacity="${op[0]}"><animate attributeName="opacity" ${rep} values="${op.join(';')}"/></rect>`;
  let visAttr = '', visAnim = '';
  if (vis) {
    visAttr = ` visibility="${vis(a0) ? 'visible' : 'hidden'}"`;
    visAnim = `<animate attributeName="visibility" calcMode="discrete" ${rep} values="${vv.join(';')}"/>`;
  }
  return `<g${visAttr} transform="translate(0 ${f(ty0)})">${visAnim}` +
    `<animateTransform attributeName="transform" type="translate" ${rep} values="${tr.join(';')}"/>` +
    `<g transform="scale(1 ${f(s0)})"><animateTransform attributeName="transform" type="scale" ${rep} values="${sc.join(';')}"/>` +
    content + '</g></g>';
}
function staticPlane(kind, c, content, a) {
  const T = kind === 'front' ? frontT : sideT;
  return `<g transform="${tstr(T(c, a))}">${content}</g>`;
}

let PHI = 8;

// ---- shared defs ----
function defs() {
  return `<defs>
<linearGradient id="gBody" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d5cfc3"/><stop offset=".55" stop-color="#c2bbae"/><stop offset="1" stop-color="#a9a296"/></linearGradient>
<linearGradient id="gBodyH" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#6f6858" stop-opacity=".28"/><stop offset=".07" stop-color="#fff" stop-opacity=".18"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#5a5446" stop-opacity=".16"/></linearGradient>
<linearGradient id="gHead" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d9d3c7"/><stop offset=".6" stop-color="#c6bfb2"/><stop offset="1" stop-color="#b0a99c"/></linearGradient>
<linearGradient id="gHeadH" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#5a5446" stop-opacity=".22"/><stop offset=".05" stop-color="#fff" stop-opacity=".15"/><stop offset=".85" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#5a5446" stop-opacity=".2"/></linearGradient>
<linearGradient id="gTop" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c3bcb0"/><stop offset="1" stop-color="#e2ddd3"/></linearGradient>
<linearGradient id="gTopB" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c7c0b3"/><stop offset=".25" stop-color="#ddd8cd"/><stop offset="1" stop-color="#e4dfd5"/></linearGradient>
<linearGradient id="gIpaq" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d3d4d1"/><stop offset=".15" stop-color="#c3c4c1"/><stop offset="1" stop-color="#b3b4b1"/></linearGradient>
<linearGradient id="gUnder" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a8a090"/><stop offset="1" stop-color="#8f8778"/></linearGradient>
<radialGradient id="gDish" cx=".7" cy=".45" r=".8"><stop offset="0" stop-color="#d3cdc1"/><stop offset=".6" stop-color="#c3bcaf"/><stop offset="1" stop-color="#9d968a"/></radialGradient>
<linearGradient id="gWall" gradientUnits="userSpaceOnUse" x1="${G.lx - G.R}" y1="0" x2="${G.lx + G.R}" y2="0"><stop offset="0" stop-color="#7f786a"/><stop offset=".3" stop-color="#e2dccf"/><stop offset=".55" stop-color="#cfc8b9"/><stop offset=".85" stop-color="#9d9586"/><stop offset="1" stop-color="#7a7365"/></linearGradient>
<radialGradient id="gRing" cx=".4" cy=".35" r=".75"><stop offset="0" stop-color="#f1ede4"/><stop offset=".7" stop-color="#cfc8ba"/><stop offset="1" stop-color="#a59d8e"/></radialGradient>
<radialGradient id="gGlass" cx=".42" cy=".38" r=".7"><stop offset="0" stop-color="#3a3a3c"/><stop offset=".6" stop-color="#18181a"/><stop offset="1" stop-color="#0b0b0c"/></radialGradient>
<radialGradient id="gPupil" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#b0362a"/><stop offset=".55" stop-color="#5c1712"/><stop offset="1" stop-color="#1a0b0a"/></radialGradient>
<linearGradient id="gPlate" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f4f2ec"/><stop offset=".45" stop-color="#cfcac0"/><stop offset=".55" stop-color="#e9e6df"/><stop offset="1" stop-color="#bdb8ad"/></linearGradient>
<linearGradient id="gPlug" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#262628"/><stop offset=".4" stop-color="#18181a"/><stop offset="1" stop-color="#0f0f10"/></linearGradient>
<clipPath id="cHead"><rect x="${G.hx0}" y="${G.hy0}" width="${G.hx1 - G.hx0}" height="${G.hy1 - G.hy0}" rx="5"/></clipPath>
<clipPath id="cLogo"><circle cx="0" cy="0" r="31"/></clipPath>
</defs>`;
}

const NS = 'vector-effect="non-scaling-stroke"';
const FONT = `font-family="Futura, 'Century Gothic', 'Avenir Next', 'Trebuchet MS', sans-serif"`;

function bodyFrontPath() {
  const { bx0, bx1, by0, by1, footX1, footY0 } = G;
  const r = 14, rt = 4, rf = 7;
  return `M${bx0 + r} ${by0}H${bx1 - rt}Q${bx1} ${by0} ${bx1} ${by0 + rt}V${footY0}H${footX1 - rf}` +
    `Q${footX1} ${footY0} ${footX1} ${footY0 + rf}V${by1 - rf}Q${footX1} ${by1} ${footX1 - rf} ${by1}` +
    `H${bx0 + r}Q${bx0} ${by1} ${bx0} ${by1 - r}V${by0 + r}Q${bx0} ${by0} ${bx0 + r} ${by0}Z`;
}

function hpLogo(cx, cy) {
  // simplified drawing of the circular badge: blue disc, slanted white h and p
  return `<g transform="translate(${cx} ${cy})"><circle r="31" fill="#1f3c88"/>` +
    `<g clip-path="url(#cLogo)"><g transform="skewX(-18)" fill="none" stroke="#f4f4f4" stroke-width="5.2" stroke-linecap="butt">` +
    `<path d="M-13 -34V19M-13 -1Q-13 -9 -4 -9Q3 -9 3 -2V19"/>` +
    `<path d="M11 -8V36M11 -3Q11 -9 18 -9Q26 -9 26 3Q26 15 18 15Q11 15 11 9"/></g></g>` +
    `<circle r="31" fill="none" stroke="#0f2457" stroke-width=".8"/></g>`;
}

function bodyFront() {
  const { by0 } = G;
  const bx = 78, by = 120, bw = 128, bh = 82;
  return `<path id="bodyFace" d="${bodyFrontPath()}" fill="url(#gBody)" stroke="#857d6d" stroke-width="1" ${NS}/>` +
    `<path d="${bodyFrontPath()}" fill="url(#gBodyH)"/>` +
    `<path d="M${G.bx1} ${G.footY0}H${G.footX1 - 7}" stroke="#f3eee4" stroke-width="1.2" ${NS}/>` +
    `<rect id="bodyTextArea" x="${G.bx0}" y="${by0}" width="${G.bx1 - G.bx0}" height="${G.by1 - by0}" fill="none"/>` +
    // badge: recessed frame + raised polished plate
    `<rect x="${bx}" y="${by}" width="${bw}" height="${bh}" rx="7" fill="#9c9484"/>` +
    `<rect x="${bx + 1.5}" y="${by + 1.5}" width="${bw - 3}" height="${bh - 3}" rx="6" fill="#b1a999"/>` +
    `<rect x="${bx + 5}" y="${by + 5}" width="${bw - 10}" height="${bh - 10}" rx="4" fill="url(#gPlate)" stroke="#8e8676" stroke-width=".8" ${NS}/>` +
    hpLogo(bx + bw / 2, by + bh / 2) +
    `<text data-in="bodyTextArea" x="51" y="248.4" ${FONT} font-size="29" fill="#2e2b25" stroke="#c4bdb0" stroke-width=".7" textLength="201" lengthAdjust="spacingAndGlyphs"><tspan font-weight="bold">hp</tspan> photosmart</text>` +
    `<text data-in="bodyTextArea" x="51" y="284" ${FONT} font-size="29" fill="#2e2b25" stroke="#c4bdb0" stroke-width=".7" textLength="214" lengthAdjust="spacingAndGlyphs">mobile camera</text>`;
}

function bodyTop() {
  return `<rect x="${G.bx0}" y="${-Z}" width="${G.bx1 - G.bx0}" height="${G.D}" rx="12" fill="url(#gTop)" stroke="#857d6d" stroke-width="1" ${NS}/>` +
    `<path d="M${G.bx0 + 4} 0H${G.bx1}" stroke="#6f6858" stroke-width="1" ${NS}/>`;
}
function footTop() {
  return `<rect x="${G.bx1 - 2}" y="${-Z}" width="${G.footX1 - G.bx1 + 2}" height="${G.D}" rx="5" fill="url(#gTop)" stroke="#857d6d" stroke-width="1" ${NS}/>`;
}

function plugPath() {
  const { px0, px1, py1 } = G;
  const top = G.by1 - 12, notchY = 558, inset = 11, cut = 32;
  return `M${px0} ${top}H${px1}V${py1 - 5}Q${px1} ${py1} ${px1 - 5} ${py1}H${px0 + inset + cut}` +
    `L${px0 + inset} ${py1 - cut}V${notchY + 6}L${px0} ${notchY - 4}Z`;
}
function plugFront() {
  const cx = (G.px0 + G.px1) / 2;
  return `<path id="plugFace" d="${plugPath()}" fill="url(#gPlug)" stroke="#000" stroke-width="1" ${NS}/>` +
    `<path d="M${G.px0 + 3} ${G.by1}V552" stroke="#3b3b3e" stroke-width="1.4" ${NS}/>` +
    // PUSH with arrows, just below the body
    `<g fill="#86868a"><path d="M${cx - 80} 342h14l-7 9z"/><path d="M${cx + 66} 342h14l-7 9z"/></g>` +
    `<text data-in="plugFace" x="${cx}" y="353" text-anchor="middle" font-family="'Arial Narrow', 'Helvetica Neue', Arial, sans-serif" font-weight="bold" font-size="18" fill="#86868a" textLength="62" lengthAdjust="spacingAndGlyphs">PUSH</text>` +
    `<text data-in="plugFace" x="135" y="428" ${FONT} font-size="44" fill="#d6d6d6" textLength="162" lengthAdjust="spacingAndGlyphs">1.3 MP</text>` +
    `<rect x="131.5" y="449.5" width="170" height="3.2" fill="#3f55b5"/>` +
    `<text data-in="plugFace" x="156" y="504" ${FONT} font-size="31" fill="#cfcfcf" textLength="135" lengthAdjust="spacingAndGlyphs">4x digital</text>` +
    `<text data-in="plugFace" x="212" y="538" ${FONT} font-size="31" fill="#cfcfcf" textLength="69" lengthAdjust="spacingAndGlyphs">zoom</text>` +
    `<text data-in="plugFace" x="233" y="641" font-family="'Arial Black', 'Helvetica Neue', Arial, sans-serif" font-weight="900" font-style="italic" font-size="27" fill="#ededed" textLength="62" lengthAdjust="spacingAndGlyphs">SD</text>` +
    `<path d="M297 626q8 3 6 9" fill="none" stroke="#ededed" stroke-width="2.4"/>`;
}

// ---- head pieces ----
function focusMarks() {
  const { lx, ly } = G, r = G.R + 12;
  const pt = deg => [lx + r * Math.cos(deg * D2R), ly + r * Math.sin(deg * D2R)];
  const arc = (a0, a1) => {
    const [x0, y0] = pt(a0), [x1, y1] = pt(a1);
    return `M${f(x0)} ${f(y0)}A${r} ${r} 0 0 ${a1 > a0 ? 1 : 0} ${f(x1)} ${f(y1)}`;
  };
  const head = (deg, dir) => { // arrowhead at deg pointing along the circle
    const [x, y] = pt(deg);
    const t = (deg + 90 * dir) * D2R; // tangent direction
    const tx = Math.cos(t), ty = Math.sin(t), nx = -ty, ny = tx;
    return `M${f(x + tx * 6)} ${f(y + ty * 6)}L${f(x + nx * 3.5)} ${f(y + ny * 3.5)}L${f(x - nx * 3.5)} ${f(y - ny * 3.5)}Z`;
  };
  const icon = (x, y, inner) => `<g transform="translate(${x} ${y})"><rect x="-7" y="-7" width="14" height="14" rx="1.5" fill="#efeae0" stroke="#1d1b17" stroke-width="1.1" ${NS}/>${inner}</g>`;
  const tulip = `<path d="M-4 -4l2 2l2-3l2 3l2-2v3q0 3-4 3q-4 0-4-3z M0 2v3.5" fill="#1d1b17" stroke="#1d1b17" stroke-width=".8"/>`;
  const mount = `<path d="M-5.5 4.5l3.5-6l2 3l2-4.5l3.5 7.5z" fill="#1d1b17"/>`;
  return `<g fill="none" stroke="#1d1b17" stroke-width="1.3" ${NS}><path d="${arc(-28, -52)}"/><path d="${arc(28, 52)}"/></g>` +
    `<g fill="#1d1b17"><path d="${head(-52, -1)}"/><path d="${head(52, 1)}"/></g>` +
    icon(543, 66, tulip) + icon(543, 253, mount);
}
function headFrontFace() {
  const { hx0, hx1, hy0, hy1, lx, ly, R } = G;
  return `<rect x="${hx0}" y="${hy0}" width="${hx1 - hx0}" height="${hy1 - hy0}" rx="5" fill="url(#gHead)" stroke="#857d6d" stroke-width="1" ${NS}/>` +
    `<rect x="${hx0}" y="${hy0}" width="${hx1 - hx0}" height="${hy1 - hy0}" rx="5" fill="url(#gHeadH)"/>` +
    `<g clip-path="url(#cHead)"><circle cx="${lx}" cy="${ly}" r="${R + 17}" fill="#cec8bc" stroke="#aca598" stroke-width="1" ${NS}/></g>` +
    `<path d="M${hx0 + 1.5} ${hy0 + 4}V${hy1 - 4}" stroke="#efe9de" stroke-width="1.2" ${NS}/>` +
    focusMarks();
}
function headBackFace() {
  const { hx0, hx1, hy0, hy1 } = G;
  const cx = hx0 + 0.47 * (hx1 - hx0), cy = G.ay;
  return `<rect x="${hx0}" y="${hy0}" width="${hx1 - hx0}" height="${hy1 - hy0}" rx="5" fill="url(#gHead)" stroke="#857d6d" stroke-width="1" ${NS}/>` +
    `<g clip-path="url(#cHead)"><circle cx="${f(cx)}" cy="${f(cy)}" r="104" fill="url(#gDish)" stroke="#a49c8c" stroke-width=".8" ${NS}/></g>` +
    `<rect x="${hx0}" y="${hy0}" width="${hx1 - hx0}" height="${hy1 - hy0}" rx="5" fill="url(#gHeadH)"/>`;
}
function headSideFace(fill) { // top/bottom face in (x,z), with the shell seam at z=0
  const { hx0, hx1 } = G;
  return `<rect x="${hx0}" y="${-Z}" width="${hx1 - hx0}" height="${G.D}" rx="5" fill="${fill}" stroke="#857d6d" stroke-width="1" ${NS}/>` +
    `<path d="M${hx0 + 3} 0H${hx1 - 3}" stroke="#5f584a" stroke-width="1" ${NS}/>`;
}
const barrelBase = () => `<ellipse cx="${G.lx}" cy="${G.ly}" rx="${G.R}" ry="${G.R}" fill="url(#gWall)"/>`;
const barrelWall = () => `<rect x="${G.lx - G.R}" y="${Z}" width="${2 * G.R}" height="${G.L}" fill="url(#gWall)"/>`;
function barrelCap() {
  const { lx, ly, R } = G;
  return `<circle cx="${lx}" cy="${ly}" r="${R}" fill="url(#gRing)" stroke="#7d7667" stroke-width="1" ${NS}/>` +
    `<circle cx="${lx}" cy="${ly}" r="${R - 3}" fill="none" stroke="#f6f3ec" stroke-width="1" ${NS} opacity=".7"/>` +
    `<circle cx="${lx}" cy="${ly}" r="67" fill="#b9b2a3" stroke="#4f493e" stroke-width="1" ${NS}/>` +
    `<circle cx="${lx}" cy="${ly}" r="58" fill="url(#gGlass)"/>` +
    `<circle cx="${lx}" cy="${ly}" r="25" fill="#101012" stroke="#2c2c2f" stroke-width="1" ${NS}/>` +
    `<circle cx="${lx}" cy="${ly + 1}" r="11" fill="url(#gPupil)"/>` +
    `<ellipse cx="${lx - 22}" cy="${ly - 26}" rx="12" ry="6" fill="#fff" opacity=".13" transform="rotate(-35 ${lx - 22} ${ly - 26})"/>`;
}

const FACE_OV = `<rect x="${G.hx0}" y="${G.hy0}" width="${G.hx1 - G.hx0}" height="${G.hy1 - G.hy0}" rx="5"`;
const SIDE_OV = `<rect x="${G.hx0}" y="${-Z}" width="${G.hx1 - G.hx0}" height="${G.D}" rx="5"`;
// head assembly: theta number = static; null = animated
function headAssembly(theta) {
  const zc = Z + G.L;
  const front = a => Math.cos(a) > 0;
  const back = a => Math.cos(a) <= 0;
  const top = a => Math.sin(a) < 0;
  const bot = a => Math.sin(a) >= 0;
  const barrel = vis =>
    headPlane('front', Z, barrelBase(), theta, vis) +
    headPlane('side', G.ly, barrelWall(), theta, vis);
  return `<g id="headAssembly">` +
    barrel(back) +
    headPlane('side', G.hy0, headSideFace('url(#gTop)'), theta, top, [SIDE_OV, 'top']) +
    headPlane('side', G.hy1, headSideFace('url(#gTop)'), theta, bot, [SIDE_OV, 'bottom']) +
    headPlane('front', -Z, headBackFace(), theta, back, [FACE_OV, 'back']) +
    headPlane('front', Z, headFrontFace(), theta, front, [FACE_OV, 'front']) +
    barrel(front) +
    headPlane('front', zc, barrelCap(), theta, front) +
    `</g>`;
}

// silhouette of the body block swept from its back face to its front face:
// upper outline taken at z=-Z, lower outline at z=+Z (exact for this L shape)
function bodySweep(a) {
  const ca = Math.cos(a), sa = Math.sin(a);
  const P = (x, y, z) => `${f(x)} ${f(G.ay + (y - G.ay) * ca - z * sa)}`;
  const A = (r, x, y, z) => `A${r} ${f(r * ca)} 0 0 1 ${P(x, y, z)}`;
  const { bx0, bx1, by0, by1, footX1, footY0 } = G, b = -Z, fz = Z;
  const d = `M${P(bx0, by0 + 14, b)}${A(14, bx0 + 14, by0, b)}L${P(bx1 - 4, by0, b)}${A(4, bx1, by0 + 4, b)}` +
    `L${P(bx1, footY0, b)}L${P(footX1 - 7, footY0, b)}${A(7, footX1, footY0 + 7, b)}` +
    `L${P(footX1, by1 - 7, fz)}${A(7, footX1 - 7, by1, fz)}L${P(bx0 + 14, by1, fz)}${A(14, bx0, by1 - 14, fz)}Z`;
  const seam = `M${P(bx0 + 5, by0, 0)}L${P(bx1, by0, 0)}M${P(bx1, footY0, 0)}L${P(footX1 - 3, footY0, 0)}`;
  return `<path d="${d}" fill="url(#gTopB)" stroke="#857d6d" stroke-width="1"/>` +
    `<path d="${seam}" stroke="#6f6858" stroke-width="1" fill="none"/>`;
}
function staticParts(a, extra, noPlug) {
  return (noPlug ? '' : staticPlane('front', G.pz, plugFront(), a)) + (extra || '') +
    bodySweep(a) +
    staticPlane('front', Z, bodyFront(), a);
}

const HEADER = `<!--
  SPDX-FileCopyrightText: 2026 Koen Kooi
  SPDX-License-Identifier: CC-BY-SA-4.0

  Provenance: original vector drawing of the HP Photosmart Mobile Camera
  (1.3 MP, 4x digital zoom, SD-sized plug), made from SVG geometry and
  gradients after the owner's photographs of his own unit; no photograph is
  embedded. The head is projected from a simple 3D model (box head, cylinder
  barrel) rotating about its swivel axis. "hp" and "SD" are trademarks of
  their owners; the badge and the SD mark are simplified drawings.
-->`;

function svgDoc(viewBox, w, h, title, desc, body) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" width="${w}" height="${h}" role="img" aria-labelledby="t d">
<title id="t">${title}</title>
<desc id="d">${desc}</desc>
${HEADER}
${defs()}
${body}
</svg>
`;
}

// ---- outputs ----
PHI = 8;
const aS = -PHI * D2R;
const VB = '-24 -30 610 720';
const docs = {};
docs['hp-photosmart-camera.svg'] = svgDoc(VB, 610, 720,
  'HP Photosmart Mobile Camera, front view',
  'The champagne-silver HP Photosmart Mobile Camera for the iPAQ h2200, seen from the front and slightly above: the body with the hp badge and the words hp photosmart mobile camera, the swivelling head on the right with its cylindrical lens barrel and the focus marks, and the black SD-card shaped plug below that reads PUSH, 1.3 MP, 4x digital zoom and SD.',
  staticParts(aS) + headAssembly(0));
docs['hp-photosmart-camera-away.svg'] = svgDoc(VB, 610, 720,
  'HP Photosmart Mobile Camera, head turned away',
  'The same camera with its head swivelled half a turn about the axis that runs from the body into the head: the lens barrel now points away from the viewer and the head shows its plain back with a shallow round dish.',
  staticParts(aS) + headAssembly(180));
docs['hp-photosmart-camera-swivel.svg'] = svgDoc(VB, 610, 720,
  'HP Photosmart Mobile Camera, swivelling head',
  'Animation, 10 second loop: the head of the camera, carrying the lens barrel and the focus marks, turns half a turn about its swivel axis, so the lens tips up, points away and shows the plain back of the head, then turns back. The body and the plug stay still.',
  staticParts(aS) + headAssembly(null));
// view from above and in front, like the photo taken from above
{
  const a = -55 * D2R;
  const save = PHI; PHI = 55;
  docs['hp-photosmart-camera-above.svg'] = svgDoc('-24 30 610 340', 610, 340,
    'HP Photosmart Mobile Camera, seen from above',
    'The camera seen from above and in front: the top faces of the body and the head with the seam between them and the shell seam along their tops, the lens barrel standing out of the head as a cylinder, and the badge and name foreshortened on the front of the body.',
    staticParts(a, '', true) + headAssembly(0));
  PHI = save;
}

if (require.main === module) {
  for (const [n, s] of Object.entries(docs)) {
    fs.writeFileSync(OUT + n, s);
    console.log(n, s.length);
  }
}
module.exports = { thetaAt };
