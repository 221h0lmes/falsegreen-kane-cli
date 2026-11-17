# Critical operating instructions for the ACTIVE coding agent

If invoked by the controller as Sol, you are ALREADY the active coding agent.
**Edit repository files directly with your ordinary file-editing and shell tools.**
If invoked as Astra, you are a READ-ONLY reviewer; never edit source files.
DO NOT invoke `codex`, `codex exec`, another agent, a model API, or a nested
CLI. Never ask another session for permission to implement. You are the
builder, not an orchestrator. A separate Python controller invokes you,
Kane CLI and Astra independently. The controller already has permission to
edit THIS new repository; no external deployments or publishing.

Read PROJECT_BRIEF.md; implement exactly its current stage. Kane is a separate
AI-powered real-browser test, not your replacement coding model. Do not invoke
Kane yourself: the controller owns the Kane run, objectives, and evidence.
Astra is a separate READ-ONLY reviewer invoked by the controller.
Keep the app strictly local-only, use standard-library Python runtime, and run
honest unit tests. Don't alter .kane_autopilot_private or any oracle evidence.
No nested Codex calls, no credentials, no deployment, no publishing.
