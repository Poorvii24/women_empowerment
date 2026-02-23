Mission: Invisible Skill Intelligence System (ISIS)
1. Core Architectural Strategy
Orchestration: Use Antigravity’s Manager View to run parallel sessions: Claude Code for the API/Backend and Gemini for the UI/Styling.

Intelligence Layer: Implement Gemini 3.1 Pro via API to perform Zero-Shot Semantic Mapping of unstructured user inputs to professional O*NET skill standards.

State Management: Utilize a lightweight SQLite database to track the evolution of a user's Leadership Index over time.

2. Technical Tasks & Agent Assignment
Phase 1: Foundation (Assigned to: Claude Code)
Backend Setup: Initialize a Python Flask server with endpoints for POST /analyze_activity and GET /dashboard_metrics.

Data Schema: Design an SQLite schema storing user_id, input_activity, mapped_skill, and skill_magnitude.

Skill Dataset: Integrate a JSON-based reference of professional skills for the "Analytics Engine" to reference.

Phase 2: The Intelligence Engine (Assigned to: Gemini)
NLP Pipeline: Build the prompt chain that takes raw text (e.g., "managing household budget") and returns a structured JSON including Transferable Skill, Estimated Market Value, and Leadership Category.

Scoring Logic: Implement the Weighted Scoring Formula for the Leadership Index based on decision-making intensity.

Phase 3: Frontend & Visualization (Assigned to: Gemini)
Responsive Dashboard: Create a "Professional Portfolio" UI using Bootstrap with a heavy focus on data visualization.

Magic Charts: Implement Chart.js spider/radar charts to visually map "Invisible Skills" into a professional hierarchy.

3. Success Metrics for the Finals
Accuracy: The AI must consistently translate "unpaid activities" into professional terminology without losing context.

Documentation: Automatically generate a Resume Summary Statement based on the computed Employability Score.

Finals Polish: Ensure the UI is clean, empowering, and optimized for a 3-minute live demo.

How to Use This in Antigravity