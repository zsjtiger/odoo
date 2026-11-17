# Odoo AI chat on mobile: plan

## Current state

- The AI chat is a mail `ChatWindow` with an AI-specific composer (`addons/ai/static/src/discuss/chat_window_patch.js`, `chat.scss`).
- Mail already switches a chat window to a full-screen layout when `ui.isSmall` is true: the `o-mobile` class sets `w-100 h-100` (`addons/mail/static/src/core/common/chat_window.js`, `chat_window.scss`). The AI window inherits this.
- The floating window in the screenshot (fixed width, rounded frame, fold/expand/close buttons) is therefore the desktop variant. The AI-specific rules in `chat.scss` only apply when the window is not `o-mobile`.
- The gaps are in the AI-specific UI, which has been designed for desktop. Nothing has been checked on a real phone yet.

## What to change

1. **Viewport and keyboard**
   - Use `100dvh` for the full-screen height and `env(safe-area-inset-bottom)` for the composer padding, so the composer stays above the iOS and Android home bar.
   - Check that the composer stays visible when the virtual keyboard opens.

2. **Empty state and suggestion chips** (the greeting and the "Do I have any customer..." chip in the screenshot)
   - Chips take the full width and wrap, with a minimum tap target of 44px.
   - Keep the greeting from pushing the composer off screen on short devices (360x640).

3. **Composer**
   - Input font size at least 16px, otherwise iOS zooms the page on focus.
   - The microphone button needs a 44px target.
   - Voice input on mobile browsers needs a user gesture, a secure context (HTTPS) and microphone permission. Confirm the existing focus guard in `composer_patch.js` still works while recording.

4. **Header and chrome**
   - On `o-mobile`, show only the back or close action. Hide the desktop fold and expand controls.
   - The agent panel (`ai_agent_panel`, fixed 420px) is only used in Discuss on desktop, so it does not need a mobile layout. Confirm it stays hidden on small screens.

5. **Messages**
   - Tables already scroll horizontally (`ai-table-response`). Check code blocks (`ai-code-response`, `min-width: max-content`) inside the full-width layout.
   - The `max-width: 1500px` rule already makes messages full width on small screens. Confirm this on phones.

6. **Layering**
   - Dialogs, the file viewer and the web-page preview must open above the full-screen AI window. `chat.scss` already raises their z-index when an AI chat is open. Verify this on mobile.

7. **Entry points**
   - The AI systray button is inside the navbar, which collapses into the burger menu on mobile. Confirm it can still open a chat there.
   - The chatter and editor entry points already branch on `isSmall`. Confirm they open the full-screen window.

## Verification

- Playwright with a mobile viewport (390x844 and 360x640, `isMobile` and `hasTouch`) using the bundled Chromium at `/opt/pw-browsers`.
- Screenshots of: empty state, a response with a table and code, the composer while recording, a dialog opened from the chat.
- Add a tour test that runs at mobile width for the main flow (open chat, ask a question, read the answer).
- Manual check on one iOS Safari and one Android Chrome device, mainly for voice input and keyboard behavior, which emulation does not cover well.

## Risks and open questions

- Voice input on iOS Safari is the biggest risk. The realtime transcription client may need a different start flow there.
- Decide whether the desktop floating window should remain the default on tablets (for example, iPad landscape at width above the `md` breakpoint). Mail's `isSmall` threshold decides this.
