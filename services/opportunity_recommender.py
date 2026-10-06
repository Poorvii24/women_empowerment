"""
services/opportunity_recommender.py
=====================================
Recommends concrete, externally-verifiable opportunities tailored to the
user's target role and weakest skill gaps.

Categories:
    projects        – things to build, with GitHub-hostable output
    hackathons      – platforms/events where they can compete
    certifications  – industry-recognised credentials worth pursuing now
    open_source     – first OSS contribution targets appropriate for the role
    learning        – curated free resources (one per category, not overwhelming)
"""
from services.role_taxonomy import list_target_roles

_ROLE_OPPS = {
    "AI Engineer": {
        "projects": [
            {"title": "End-to-end NLP pipeline with HuggingFace + FastAPI",
             "description": "Fine-tune a small transformer on a public dataset, expose it as an API, and deploy it to Hugging Face Spaces.",
             "url": "https://huggingface.co/spaces", "difficulty": "Intermediate"},
            {"title": "Image classification model with ONNX export",
             "description": "Train with PyTorch, export to ONNX, serve with FastAPI — shows production awareness.",
             "url": "https://pytorch.org/tutorials/", "difficulty": "Intermediate"},
            {"title": "Build ISIS's own skill-classification fine-tuned model",
             "description": "Use your own project's activity dataset to fine-tune a sentence-transformers model for skill classification.",
             "url": "https://www.sbert.net/docs/training/overview.html", "difficulty": "Advanced"},
        ],
        "hackathons": [
            {"title": "Google AI Hackathon", "url": "https://ai.google.dev/competition", "frequency": "Annual"},
            {"title": "Devpost AI Track", "url": "https://devpost.com/hackathons?challenge_type[]=AI", "frequency": "Ongoing"},
            {"title": "HackerEarth ML Challenges", "url": "https://www.hackerearth.com/challenges/", "frequency": "Monthly"},
        ],
        "certifications": [
            {"title": "TensorFlow Developer Certificate", "provider": "Google",
             "url": "https://www.tensorflow.org/certificate", "cost": "~$100"},
            {"title": "AWS Certified Machine Learning – Specialty", "provider": "AWS",
             "url": "https://aws.amazon.com/certification/certified-machine-learning-specialty/", "cost": "~$300"},
            {"title": "DeepLearning.AI Short Courses (free)", "provider": "DeepLearning.AI",
             "url": "https://learn.deeplearning.ai", "cost": "Free"},
        ],
        "open_source": [
            {"title": "Contribute to HuggingFace Transformers", "url": "https://github.com/huggingface/transformers/contribute",
             "why": "Good first issues labelled — massive visibility in the AI community"},
            {"title": "Add a dataset card to HuggingFace Datasets", "url": "https://huggingface.co/datasets",
             "why": "Fastest OSS contribution for an AI profile — 1–2 hours"},
        ],
        "learning": [
            {"title": "Papers With Code (read/implement one paper per month)", "url": "https://paperswithcode.com"},
            {"title": "fast.ai Practical Deep Learning (free)", "url": "https://course.fast.ai"},
        ],
    },
    "Data Scientist": {
        "projects": [
            {"title": "End-to-end Kaggle competition notebook",
             "description": "EDA → feature engineering → ensemble model → submission + write-up. Shows the full DS lifecycle.",
             "url": "https://www.kaggle.com/competitions", "difficulty": "Beginner"},
            {"title": "SQL + Python analytics dashboard",
             "description": "Pull a public dataset (e.g. NYC taxi data), analyze in Python/SQL, visualise with Streamlit.",
             "url": "https://docs.streamlit.io", "difficulty": "Intermediate"},
            {"title": "A/B test simulation and analysis report",
             "description": "Simulate an A/B experiment, apply proper statistical tests, write up findings as a stakeholder report.",
             "url": "https://www.kaggle.com/learn", "difficulty": "Intermediate"},
        ],
        "hackathons": [
            {"title": "Kaggle Competitions", "url": "https://www.kaggle.com/competitions", "frequency": "Ongoing"},
            {"title": "Analytics Vidhya Hackathons", "url": "https://datahack.analyticsvidhya.com/", "frequency": "Monthly"},
            {"title": "DrivenData", "url": "https://www.drivendata.org/competitions/", "frequency": "Ongoing"},
        ],
        "certifications": [
            {"title": "Google Professional Data Analyst Certificate", "provider": "Google/Coursera",
             "url": "https://www.coursera.org/professional-certificates/google-data-analytics", "cost": "~$200"},
            {"title": "IBM Data Science Professional Certificate", "provider": "IBM/Coursera",
             "url": "https://www.coursera.org/professional-certificates/ibm-data-science", "cost": "~$200"},
        ],
        "open_source": [
            {"title": "Contribute to Pandas", "url": "https://github.com/pandas-dev/pandas/contribute",
             "why": "Widely-used — first issues well-documented"},
            {"title": "Add an example notebook to scikit-learn", "url": "https://github.com/scikit-learn/scikit-learn",
             "why": "Well-maintained project with clear contributing guide"},
        ],
        "learning": [
            {"title": "Kaggle Learn (free, interactive)", "url": "https://www.kaggle.com/learn"},
            {"title": "Towards Data Science Medium publication", "url": "https://towardsdatascience.com"},
        ],
    },
    "ML Engineer": {
        "projects": [
            {"title": "ML model served with FastAPI + Docker + CI/CD",
             "description": "Take any trained model and build a production-grade serving stack with tests, Docker, and GitHub Actions.",
             "url": "https://fastapi.tiangolo.com", "difficulty": "Intermediate"},
            {"title": "Implement a feature store with Redis",
             "description": "Build a simple feature store that pre-computes and caches ML features, demonstrating MLOps thinking.",
             "url": "https://redis.io/docs/latest/", "difficulty": "Advanced"},
        ],
        "hackathons": [
            {"title": "MLH (Major League Hacking)", "url": "https://mlh.io/seasons/2025/events", "frequency": "Weekly"},
            {"title": "Devfolio Hackathons", "url": "https://devfolio.co/hackathons", "frequency": "Ongoing"},
        ],
        "certifications": [
            {"title": "AWS Certified ML Specialty", "provider": "AWS",
             "url": "https://aws.amazon.com/certification/certified-machine-learning-specialty/", "cost": "~$300"},
            {"title": "Databricks Certified ML Associate", "provider": "Databricks",
             "url": "https://www.databricks.com/learn/certification/machine-learning-associate", "cost": "~$200"},
        ],
        "open_source": [
            {"title": "MLflow — first issues", "url": "https://github.com/mlflow/mlflow/contribute",
             "why": "Core MLOps tool — high resume visibility"},
            {"title": "BentoML contributions", "url": "https://github.com/bentoml/BentoML/contribute",
             "why": "Model serving framework — directly relevant to ML Engineer role"},
        ],
        "learning": [
            {"title": "Made With ML (free MLOps course)", "url": "https://madewithml.com"},
            {"title": "Full Stack Deep Learning (free)", "url": "https://fullstackdeeplearning.com/course/2022/"},
        ],
    },
    "Cloud Engineer": {
        "projects": [
            {"title": "3-tier web app on AWS with Terraform",
             "description": "Deploy a VPC + ALB + EC2 autoscaling group + RDS setup using Terraform. Document with architecture diagram.",
             "url": "https://registry.terraform.io", "difficulty": "Intermediate"},
            {"title": "Kubernetes cluster on GKE with Helm",
             "description": "Set up a GKE cluster, deploy a sample app with Helm, add HPA and monitoring with Prometheus.",
             "url": "https://helm.sh/docs/intro/quickstart/", "difficulty": "Advanced"},
        ],
        "hackathons": [
            {"title": "AWS Build On (annual hackathon)", "url": "https://aws.amazon.com/events/", "frequency": "Annual"},
            {"title": "Google Cloud Next Hackathon", "url": "https://cloud.google.com/events", "frequency": "Annual"},
        ],
        "certifications": [
            {"title": "AWS Solutions Architect Associate", "provider": "AWS",
             "url": "https://aws.amazon.com/certification/certified-solutions-architect-associate/", "cost": "~$150"},
            {"title": "Google Professional Cloud Architect", "provider": "Google Cloud",
             "url": "https://cloud.google.com/certification/cloud-architect", "cost": "~$200"},
            {"title": "CKA — Certified Kubernetes Administrator", "provider": "CNCF",
             "url": "https://training.linuxfoundation.org/certification/certified-kubernetes-administrator-cka/", "cost": "~$395"},
        ],
        "open_source": [
            {"title": "Terraform providers — first issues", "url": "https://github.com/hashicorp/terraform/contribute",
             "why": "Core IaC tool — well-labelled beginner issues"},
            {"title": "Kubernetes documentation improvements", "url": "https://github.com/kubernetes/website/contribute",
             "why": "Easiest first OSS contribution — purely content/docs"},
        ],
        "learning": [
            {"title": "A Cloud Guru (free tier)", "url": "https://acloudguru.com"},
            {"title": "Google Cloud Skills Boost (free labs)", "url": "https://cloudskillsboost.google"},
        ],
    },
    "Backend Developer": {
        "projects": [
            {"title": "Full-featured REST API: auth + CRUD + tests + CI/CD",
             "description": "Build a FastAPI or Flask project with JWT auth, PostgreSQL, pytest tests, and a GitHub Actions CI pipeline.",
             "url": "https://fastapi.tiangolo.com", "difficulty": "Intermediate"},
            {"title": "Real-time notifications with WebSockets + Redis Pub/Sub",
             "description": "Extend any existing project to add real-time server-push notifications — demonstrates async and caching knowledge.",
             "url": "https://redis.io/docs/latest/develop/interact/pubsub/", "difficulty": "Intermediate"},
        ],
        "hackathons": [
            {"title": "MLH Global Hack Week", "url": "https://mlh.io", "frequency": "Periodic"},
            {"title": "HackerEarth Backend Challenges", "url": "https://www.hackerearth.com/challenges/", "frequency": "Monthly"},
        ],
        "certifications": [
            {"title": "AWS Certified Developer – Associate", "provider": "AWS",
             "url": "https://aws.amazon.com/certification/certified-developer-associate/", "cost": "~$150"},
            {"title": "MongoDB Developer Certification", "provider": "MongoDB",
             "url": "https://university.mongodb.com/certification", "cost": "Free (exam fee applies)"},
        ],
        "open_source": [
            {"title": "FastAPI first issues", "url": "https://github.com/fastapi/fastapi/contribute",
             "why": "Popular modern framework — active maintainers, beginner-friendly"},
            {"title": "Flask extensions — first issues", "url": "https://github.com/pallets/flask/contribute",
             "why": "You already use Flask — contributing is directly relevant to your stack"},
        ],
        "learning": [
            {"title": "roadmap.sh Backend Roadmap", "url": "https://roadmap.sh/backend"},
            {"title": "Hussein Nasser Backend Engineering (YouTube)", "url": "https://www.youtube.com/@hnasr"},
        ],
    },
}


def get_opportunities(role_name: str, missing_skills: list[dict]) -> dict:
    """
    Returns tailored opportunities for the given target role.
    `missing_skills` is used to optionally surface a skill-specific tip in the
    first project recommendation — but all recommendations are role-based, not
    purely gap-based (the gap drives the learning plan; opportunities are
    broader career development moves).
    """
    if role_name not in _ROLE_OPPS:
        # Graceful fallback for any unlisted role
        return {
            "projects": [],
            "hackathons": [{"title": "Devfolio", "url": "https://devfolio.co/hackathons", "frequency": "Ongoing"}],
            "certifications": [],
            "open_source": [],
            "learning": [],
        }

    opps = _ROLE_OPPS[role_name].copy()

    # If the user is missing core skills, surface the most critical one as
    # a personalised note on the first project recommendation
    core_missing = [s["skill"] for s in missing_skills if s.get("tier") == "core"]
    if core_missing and opps["projects"]:
        opps["projects"][0] = dict(opps["projects"][0])
        opps["projects"][0]["priority_note"] = (
            f'A good place to start: "{core_missing[0]}" — this is one of the most useful skills '
            "to pick up for this role, and this project is a great way to practice it."
        )

    return opps
