SAMRAKSHA KENDRA - MOBILE COMPANION KIT

WHAT IT ADDS
- React Native / Expo Android and iOS companion in mobile-app/
- Overview metrics using the existing deployed API
- Public-health Evidence Assistant with send button/Enter and data citations
- WHO/NCDC source status and source links
- Starter interface localization: English, Telugu, Kannada and Hindi
- API safety tests, mobile test command, Android JS bundle export, and GitHub Actions check

INSTALL
1. Extract this ZIP into the project root (C:\Users\Mahit\SamrakshaKendra).
2. Open PowerShell in that project root and run:
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Finish_Mobile_Companion.ps1
3. The script installs npm dependencies, runs tests, checks Expo compatibility, exports the Android JS bundle, and commits/pushes only mobile app/docs/workflow files if all prior steps pass.
4. To run on your phone after successful installation:
   cd mobile-app
   npx expo start
   Scan the QR code with Expo Go. Use a development build if your Expo Go version does not support SDK 57.

SAFETY / LIMITS
- No database URL, admin password, auth token, or private data is embedded in the mobile client.
- The app calls the existing public aggregate APIs and existing deterministic Evidence Assistant.
- This builds/tests a mobile companion MVP; it is not a store-ready APK/IPA and needs actual phone testing.
- It does not implement MobileNetV2 image classification or a generative LLM/RAG pipeline.
- Public surveillance counters are scoped to the dataset loaded by Samraksha Kendra, not national real-time totals.
