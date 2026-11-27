# Mobile Web Theme

Colors and style tokens for the Mobile Web client.

- `static/src/scss/theme.scss`: the values. Change a value to change the look.
- `mobile_web/static/src/styles/00_tokens.scss`: the token names and the default values.
- `mobile_web/static/src/core/theme.js`: reads the palettes (calendar, home) from CSS variables.

To make another theme, copy this module, change the values in `theme.scss`, and
depend on it instead of this module. Only one theme module should be installed.
