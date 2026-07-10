# Dark-Neon Design Spec — distilled from motionsites.ai public taxonomy

Derived from ~390 public template + background names (names/categories are public
marketing content; the 325 prompt texts are paywalled via Supabase RLS and were NOT
accessed). The names themselves encode the design language.

## Effect families (by frequency in the taxonomy)
1. **Neon / Glow** — Neon Logic, Neon Flux, Neon Pulse, Ember Glow, Thermal Glow.
   → glowing borders, text, and accents; box-shadow bloom is the primary "elevation".
2. **Aurora / Cosmic / Nebula** — Aurora Drift/Waves/Silk, Cosmic Drift/Ripple/Vortex,
   Nebula Drift, Dark Matter, Void Pulse, Black Hole Vortex, Planetary Aurora.
   → drifting multi-color radial light sources on deep space-black; ambient bg.
3. **Liquid / Fluid / Chrome** — Liquid Glass, Liquid Chrome, Liquid Motion, Fluid Motion,
   Silk Ripple, Prismatic Shift. → slow morphing gradients, iridescent sheen.
4. **Glass / Glassmorphism** — Liquid Glass Agency, Glassmorphism Hero, Glass Stream.
   → frosted translucent panels w/ blur + hairline border over the glow.
5. **3D / Depth** — 3D Story, Pulse 3D, Layered Depth, 3D Collectible. → layered z-depth,
   parallax, tilt.
6. **Portal / Vortex / Gateway** — Golden Portal, Gateway Portal, Cosmic Vortex.
   → radial focal glow, converging light.
7. **Cinematic / Dark** — Synapse Dark Hero, Obsidian Hero, Dark Portfolio, Cinematic
   Landing. → dark is DEFAULT; grain, vignette, filmic contrast.
8. **Glitch** — Glitch Pulse, Cyberpunk Reveal. → occasional accent, not everywhere.

## Motion language (from the verbs)
Dominant verbs: **Drift, Ripple, Pulse, Flow, Shift, Surge, Wave, Bloom, Trail, Storm**.
→ Motion should be **slow, ambient, continuous, looping** (8–20s) — NOT snappy.
Snappy springs are fine for direct UI feedback (button press, node drop), but the
signature feel is *drifting light* and *breathing glow*. Add ambient loops, not just
one-shot transitions.

## Color system (dark neon)
- Base: deep space black `#06080f` → panels `#0e1424` → elevated `#141c30`.
- Neon accent ramp: cyan #22d3ee, sky #38bdf8, violet #a78bfa, magenta #f472d0,
  lime #a3e635, amber #fbbf24, rose #fb7185, teal #2dd4bf.
- Primary accent = cyan; secondary = violet. Gradients cyan→violet→magenta.
- Elevation = GLOW (colored box-shadow bloom) + faint 1px luminous hairline, not
  grey drop-shadow.

## Typography
Keep Barlow (body) + Instrument Serif italic (display). Add gradient-clipped neon
headline treatment (.u-neon-text: cyan→violet). Hero copy style is bold + confident
("Unlock your AI Design Superpowers").

## Per-surface application (this app)
- **Canvas**: space-black + faint neon dot grid + ambient drifting aurora behind graph.
- **Nodes**: dark glass cards, neon accent bar w/ bloom, glowing icon chip, selected =
  bright neon ring + bloom. Type color from --node-* neon ramp.
- **Edges**: bright neon wire + blurred glow underlay + animated flow dashes when active.
- **Header**: near-black glass bar, neon logo mark, gradient CTA.
- **Palette**: dark cards, neon hover glow, icon in type color.
- **Hero/login**: full aurora-drift bg (already built) + grain + gradient headline.
- **Modals/drawers**: dark glass + neon focus ring + spring in.

## Ambient motion to ADD (the missing "slick")
- Node accent bar: slow shimmer.
- Selected node/edge: gentle breathing glow (not just static).
- Hero + empty-state: continuous aurora drift (done in canvas bg).
- Deploy CTA: slow gradient shift.
