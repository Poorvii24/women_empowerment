"""
services/learning_recommender.py
==================================
Generates a 30/60/90-day personalised learning plan based on:
  - the user's target role
  - missing skills from skill_gap_engine (prioritised: core before supporting)
  - Career Readiness Score axes (weakest axis gets highest-priority resources)

Resources are curated, not scraped — they're stable, free/freemium links that
won't vanish. Kept deliberately simple: a small per-skill resource map is
more maintainable and reliable than calling another LLM API just to get
course suggestions.
"""

# Per-skill recommendation bank.
# Key: a skill phrase from role_taxonomy (exact match, lower-cased).
# Value: list of {"title", "type", "url", "duration"} where:
#   type: "course" | "certification" | "project" | "resource"
#   duration: rough time estimate to complete

_SKILL_RESOURCES = {
    "python programming": [
        {"title": "Python for Everybody (Coursera — Michigan)", "type": "course",
         "url": "https://www.coursera.org/specializations/python", "duration": "~4 weeks"},
        {"title": "Build a CLI expense tracker", "type": "project",
         "url": "https://roadmap.sh/projects/expense-tracker", "duration": "~3 days"},
    ],
    "machine learning fundamentals": [
        {"title": "Machine Learning Specialization (Coursera — Andrew Ng)", "type": "course",
         "url": "https://www.coursera.org/specializations/machine-learning-introduction", "duration": "~3 months"},
        {"title": "Google ML Crash Course", "type": "resource",
         "url": "https://developers.google.com/machine-learning/crash-course", "duration": "~2 weeks"},
    ],
    "deep learning with neural networks": [
        {"title": "Deep Learning Specialization (Coursera — deeplearning.ai)", "type": "course",
         "url": "https://www.coursera.org/specializations/deep-learning", "duration": "~3 months"},
        {"title": "fast.ai Practical Deep Learning", "type": "course",
         "url": "https://course.fast.ai", "duration": "~7 weeks"},
    ],
    "pytorch or tensorflow": [
        {"title": "PyTorch Tutorials (official)", "type": "resource",
         "url": "https://pytorch.org/tutorials/", "duration": "~2 weeks"},
        {"title": "TensorFlow Developer Certificate", "type": "certification",
         "url": "https://www.tensorflow.org/certificate", "duration": "~2 months"},
    ],
    "data preprocessing and feature engineering": [
        {"title": "Feature Engineering for ML (Kaggle)", "type": "course",
         "url": "https://www.kaggle.com/learn/feature-engineering", "duration": "~5 hours"},
        {"title": "Build a data cleaning pipeline on Kaggle dataset", "type": "project",
         "url": "https://www.kaggle.com/datasets", "duration": "~1 week"},
    ],
    "model evaluation and validation": [
        {"title": "Hands-On Machine Learning (O'Reilly) — Ch. 2–3", "type": "resource",
         "url": "https://www.oreilly.com/library/view/hands-on-machine-learning/9781492032632/", "duration": "~1 week"},
    ],
    "rest api development": [
        {"title": "FastAPI Official Tutorial", "type": "course",
         "url": "https://fastapi.tiangolo.com/tutorial/", "duration": "~3 days"},
        {"title": "Build a REST API with Flask", "type": "project",
         "url": "https://flask.palletsprojects.com/en/stable/tutorial/", "duration": "~3 days"},
    ],
    "natural language processing": [
        {"title": "HuggingFace NLP Course (free)", "type": "course",
         "url": "https://huggingface.co/learn/nlp-course", "duration": "~4 weeks"},
        {"title": "Build a sentiment classifier on your own dataset", "type": "project",
         "url": "https://huggingface.co/datasets", "duration": "~1 week"},
    ],
    "mlops and model deployment": [
        {"title": "MLOps Specialization (Coursera — deeplearning.ai)", "type": "course",
         "url": "https://www.coursera.org/specializations/machine-learning-engineering-for-production-mlops", "duration": "~4 months"},
        {"title": "Deploy a model to Hugging Face Spaces (free)", "type": "project",
         "url": "https://huggingface.co/spaces", "duration": "~2 days"},
    ],
    "version control with git": [
        {"title": "Git & GitHub for Beginners (freeCodeCamp)", "type": "course",
         "url": "https://www.youtube.com/watch?v=RGOj5yH7evk", "duration": "~1 day"},
        {"title": "Contribute a first open-source PR", "type": "project",
         "url": "https://goodfirstissue.dev", "duration": "~1 week"},
    ],
    "cloud platforms (aws/gcp/azure)": [
        {"title": "AWS Cloud Practitioner Essentials (free)", "type": "course",
         "url": "https://aws.amazon.com/training/digital/aws-cloud-practitioner-essentials/", "duration": "~6 hours"},
        {"title": "AWS Certified Cloud Practitioner", "type": "certification",
         "url": "https://aws.amazon.com/certification/certified-cloud-practitioner/", "duration": "~1 month"},
        {"title": "Google Cloud Skills Boost (free tier)", "type": "resource",
         "url": "https://cloudskillsboost.google", "duration": "variable"},
    ],
    "docker containerization": [
        {"title": "Docker Getting Started (official)", "type": "resource",
         "url": "https://docs.docker.com/get-started/", "duration": "~2 days"},
        {"title": "Dockerize an existing Flask project", "type": "project",
         "url": "https://docs.docker.com/language/python/", "duration": "~1 day"},
    ],
    "sql and database querying": [
        {"title": "SQL for Data Science (Coursera)", "type": "course",
         "url": "https://www.coursera.org/learn/sql-for-data-science", "duration": "~4 weeks"},
        {"title": "Mode SQL Tutorial (free, interactive)", "type": "resource",
         "url": "https://mode.com/sql-tutorial/", "duration": "~1 week"},
    ],
    "statistical analysis": [
        {"title": "Statistics with Python Specialization (Coursera)", "type": "course",
         "url": "https://www.coursera.org/specializations/statistics-with-python", "duration": "~5 months"},
        {"title": "Khan Academy Statistics (free)", "type": "resource",
         "url": "https://www.khanacademy.org/math/statistics-probability", "duration": "variable"},
    ],
    "data visualization": [
        {"title": "Data Visualization with Python (Coursera — IBM)", "type": "course",
         "url": "https://www.coursera.org/learn/python-for-data-visualization", "duration": "~3 weeks"},
        {"title": "Build an interactive dashboard with Streamlit", "type": "project",
         "url": "https://docs.streamlit.io/get-started", "duration": "~3 days"},
    ],
    "infrastructure as code (terraform/cloudformation)": [
        {"title": "Terraform Getting Started (HashiCorp Learn)", "type": "course",
         "url": "https://developer.hashicorp.com/terraform/tutorials/aws-get-started", "duration": "~1 week"},
        {"title": "HashiCorp Terraform Associate Certification", "type": "certification",
         "url": "https://www.hashicorp.com/certification/terraform-associate", "duration": "~1 month"},
    ],
    "kubernetes orchestration": [
        {"title": "Kubernetes Basics (official interactive tutorial)", "type": "course",
         "url": "https://kubernetes.io/docs/tutorials/kubernetes-basics/", "duration": "~1 week"},
        {"title": "Certified Kubernetes Application Developer (CKAD)", "type": "certification",
         "url": "https://training.linuxfoundation.org/certification/certified-kubernetes-application-developer-ckad/", "duration": "~2 months"},
    ],
    "linux system administration": [
        {"title": "The Linux Command Line (free online book)", "type": "resource",
         "url": "https://linuxcommand.org/tlcl.php", "duration": "~2 weeks"},
        {"title": "Linux Foundation System Administration Essentials", "type": "course",
         "url": "https://training.linuxfoundation.org/training/linux-system-administration-essentials-lfs207/", "duration": "~1 month"},
    ],
    "ci/cd pipelines": [
        {"title": "GitHub Actions Quickstart (official)", "type": "resource",
         "url": "https://docs.github.com/en/actions/quickstart", "duration": "~1 day"},
        {"title": "Set up CI/CD for your own project using GitHub Actions", "type": "project",
         "url": "https://github.com/features/actions", "duration": "~2 days"},
    ],
    "software engineering best practices": [
        {"title": "Clean Code (Robert C. Martin) — summary", "type": "resource",
         "url": "https://gist.github.com/wojteklu/73c6914cc446146b8b533c0988cf8d29", "duration": "~2 hours"},
        {"title": "Refactor an existing project using SOLID principles", "type": "project",
         "url": "https://refactoring.guru/refactoring", "duration": "~1 week"},
    ],
    "database design and sql": [
        {"title": "Database Design Course (freeCodeCamp)", "type": "course",
         "url": "https://www.youtube.com/watch?v=ztHopE5Wnpc", "duration": "~8 hours"},
    ],
    "authentication and authorization": [
        {"title": "OAuth 2.0 & OpenID Connect (Okta blog series)", "type": "resource",
         "url": "https://developer.okta.com/blog/2019/10/21/illustrated-guide-to-oauth-and-oidc", "duration": "~3 hours"},
    ],
}

_DEFAULT_RESOURCE = {
    "title": "Search on Coursera / freeCodeCamp",
    "type": "resource",
    "url": "https://www.coursera.org",
    "duration": "variable",
}


def _lookup_resources(skill: str) -> list[dict]:
    """Find resources for a skill by normalised key matching."""
    key = skill.lower().strip()
    if key in _SKILL_RESOURCES:
        return _SKILL_RESOURCES[key]
    # Try partial key match (handles "PyTorch or TensorFlow" → "pytorch or tensorflow")
    for stored_key, resources in _SKILL_RESOURCES.items():
        if stored_key in key or key in stored_key:
            return resources
    return [_DEFAULT_RESOURCE]


def build_learning_plan(
    role_name: str,
    missing_skills: list[dict],
    partial_skills: list[dict],
    career_score,       # CareerReadinessScore dataclass
) -> dict:
    """
    Generates a 30/60/90-day learning plan.

    Strategy:
      Day 1-30  — address core missing skills (must-have for the role)
      Day 31-60 — address supporting missing + partial skills
      Day 61-90 — project recommendations, certifications, and the
                  lowest-scoring career-readiness axis

    Returns {
        "day_30": [{"skill", "resources": [...], "why"}],
        "day_60": [...],
        "day_90": [...],
    }
    """
    core_missing = [s for s in missing_skills if s.get("tier") == "core"]
    supp_missing  = [s for s in missing_skills if s.get("tier") == "supporting"]

    plan = {"day_30": [], "day_60": [], "day_90": []}

    # Day 1-30: up to 3 core missing skills
    for skill_entry in core_missing[:3]:
        skill = skill_entry["skill"]
        plan["day_30"].append({
            "skill": skill,
            "resources": _lookup_resources(skill),
            "why": f"Core requirement for {role_name} — needed for most entry-level roles.",
        })

    # Day 31-60: next 3 core missing + first 2 supporting missing + partial
    remaining_core = core_missing[3:6]
    for skill_entry in remaining_core:
        skill = skill_entry["skill"]
        plan["day_60"].append({
            "skill": skill,
            "resources": _lookup_resources(skill),
            "why": f"Core skill for {role_name} — high hiring priority.",
        })
    for skill_entry in (supp_missing[:2] + partial_skills[:2]):
        skill = skill_entry["skill"]
        plan["day_60"].append({
            "skill": skill,
            "resources": _lookup_resources(skill),
            "why": "Supporting skill that differentiates candidates at the same level.",
        })

    # Day 61-90: remaining supporting + lowest career-score axis + capstone project
    for skill_entry in supp_missing[2:5]:
        skill = skill_entry["skill"]
        plan["day_90"].append({
            "skill": skill,
            "resources": _lookup_resources(skill),
            "why": "Broadens your profile for senior roles and interviews.",
        })

    # Identify the lowest-scoring axis to suggest a targeted improvement
    axis_scores = {
        "technical": career_score.technical,
        "leadership": career_score.leadership,
        "communication": career_score.communication,
        "consistency": career_score.consistency,
        "growth": career_score.growth,
    }
    weakest_axis = min(axis_scores, key=axis_scores.get)
    axis_tips = {
        "technical": {"skill": "Build 1 end-to-end portfolio project for the target role",
                      "resources": [{"title": "roadmap.sh — role-based project ideas", "type": "project",
                                     "url": "https://roadmap.sh", "duration": "variable"}],
                      "why": "Your technical coverage is your lowest axis — a visible project closes the gap fastest."},
        "leadership": {"skill": "Take on a team coordination or mentoring role",
                       "resources": [{"title": "Google Project Management Certificate (Coursera)", "type": "course",
                                      "url": "https://www.coursera.org/professional-certificates/google-project-management",
                                      "duration": "~6 months (part-time)"}],
                       "why": "Leadership score is your weakest axis — even informal team roles count."},
        "communication": {"skill": "Write one technical blog post about a project you've built",
                          "resources": [{"title": "Hashnode (free developer blogging)", "type": "resource",
                                         "url": "https://hashnode.com", "duration": "variable"}],
                          "why": "Communication score reflects bullet quality — writing publicly sharpens articulation fast."},
        "consistency": {"skill": "Log one new activity per week for the next 8 weeks",
                        "resources": [{"title": "Set a recurring calendar reminder", "type": "resource",
                                       "url": "#", "duration": "ongoing"}],
                        "why": "Your consistency score reflects how regularly you log activities — frequency matters."},
        "growth": {"skill": "Focus on harder, higher-scope activities to raise your employability score",
                   "resources": [{"title": "Apply for a hackathon relevant to your target role", "type": "project",
                                  "url": "https://devfolio.co/hackathons", "duration": "1–2 days"}],
                   "why": "Growth score reflects whether your recent activities score higher than earlier ones."},
    }
    plan["day_90"].append(axis_tips[weakest_axis])

    # Always end with a capstone project suggestion for the role
    capstone_suggestions = {
        "AI Engineer": "Build and deploy a fine-tuned NLP model on Hugging Face Spaces",
        "Data Scientist": "Publish a full Kaggle notebook: EDA + model + insights write-up",
        "ML Engineer": "Containerise and serve a model via FastAPI + Docker + GitHub Actions CI",
        "Cloud Engineer": "Set up a 3-tier app on AWS/GCP using Terraform with autoscaling",
        "Backend Developer": "Build a production-quality REST API with auth, tests, and CI/CD",
    }
    plan["day_90"].append({
        "skill": f"Capstone project: {capstone_suggestions.get(role_name, 'Build a full-stack project for your target role')}",
        "resources": [{"title": "GitHub (host your project publicly)", "type": "project",
                       "url": "https://github.com", "duration": "2–4 weeks"}],
        "why": "A single well-documented GitHub project is the highest-ROI portfolio investment for any technical role.",
    })

    return plan
