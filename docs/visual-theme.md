# HireSense visual theme

The shared palette is defined in `frontend/src/index.css`. Deep indigo
(`#403795`) is the primary action color, inspired by the supplied reference.
White cards sit on a cool gray canvas, with tinted borders and selected states.
The existing responsive layouts, routes, focus handling and workflows are unchanged.

| Color | Use |
| --- | --- |
| Indigo | Primary buttons, branding, links, active navigation, selections and focus |
| Teal | CV scores, candidate counts and candidate details |
| Violet | Interview scores and experience weights |
| Sky | Technical-skill weights and knowledge upload section |
| Amber | Qualification weights and existing warnings |

Tailwind's existing `blue-*` utilities intentionally resolve to the shared indigo
scale. This updates current components, including portalled dropdowns and modals,
without duplicating brand styling across files. The `slate-*` scale supplies the
neutral canvas, text and borders. Native checkboxes/radios/ranges share the primary
accent; LiveKit device and meeting accents use the same palette through its theme
variables. CSS-only console buttons and tabs also reference the shared colors.

Color is decorative, not a scoring rule: score values, labels, ranks and status
wording are preserved. Green successes, amber warnings, red errors/destructive
actions and the existing blue/amber transcript speaker styling remain distinct.
No remote fonts, images, packages or backend changes are required.

Regression checks cover text contrast for primary buttons, selected navigation and
muted text, plus existing navigation, forms, dialogs, chat and interview controls.
Run `npm run test:rooms` and `npm run build` from `frontend`.
