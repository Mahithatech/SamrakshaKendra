# Samraksha Kendra Mobile Companion (Expo / React Native)

This adds an optional Android/iOS companion client that consumes the deployed, public read-only web API. It is intentionally independent from the production React/Vite frontend.

## Included features
- Overview: IDSP record, case, death, state/disease metrics and hospital directory count.
- Evidence assistant: asks the existing `/public/assistant/query` endpoint; supports Telugu, Kannada, Hindi and English for the assistant response; Enter/Send works without a question mark.
- Official sources: displays WHO and NCDC/IDSP source status and opens each official source link.
- Retry states and honest dataset disclaimer.
- No embedded admin credentials, database URL or private access token.
- Node unit tests for API URL validation, summary parsing, language input and request behavior.

## Run on Android or iOS

Use Node.js 22.13+ (the existing laptop Node 24 satisfies the requirement). SDK 57 is pinned to its compatible React and React Native versions. Expo SDK 58 has only just released, while the app-store Expo Go rollout may lag, so this kit deliberately uses the stable SDK 57 line for easier Expo Go testing. Check the official compatibility docs before upgrading: https://docs.expo.dev/versions/latest/ and https://expo.dev/changelog/sdk-57.

```powershell
cd mobile-app
npm install
npm test
npx expo install --fix
npx expo start
```

Install Expo Go on your Android phone, scan the QR code shown in the terminal/browser, and keep the laptop and phone on the same network. If the free Render backend has spun down, the first request may take longer. The default API base URL points to the deployed backend. Override it using `EXPO_PUBLIC_API_BASE_URL` only if you intentionally use another API URL.

For an Android JS bundle build check (does not create a store-ready APK):

```powershell
npm run bundle:android
```

## Validation boundaries

This is a mobile MVP source project, not an app-store release. It has not been physically tested on a user's device, and iOS builds require the corresponding Apple build workflow. Public case metrics are scoped to the current structured dataset, not national real-time totals. This mobile app does not add a MobileNetV2 image classifier and does not replace human review of outbreak reports.
