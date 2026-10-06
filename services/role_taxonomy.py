"""
services/role_taxonomy.py
============================
Static reference data: for each target career role, the skills a hiring
manager would typically expect, split into "core" (must-have) and
"supporting" (nice-to-have) tiers.

This is honestly hand-curated reference data, not a learned model — it's
the same kind of "ground truth taxonomy" a recruiter or job-description
analysis would start from. The skill_gap_engine.py module is what adds the
actual intelligence: matching a user's *unstructured* activity/resume text
against these skill labels via semantic embeddings, not simple string
matching.

Each skill name doubles as the text that gets embedded for comparison, so
they're written as natural phrases (e.g. "version control with Git") rather
than terse keywords — this measurably improves embedding match quality vs.
single-word tags.
"""

TARGET_ROLES = {
    "AI Engineer": {
        "core": [
            "Python programming",
            "machine learning fundamentals",
            "deep learning with neural networks",
            "PyTorch or TensorFlow",
            "data preprocessing and feature engineering",
            "model evaluation and validation",
            "REST API development",
        ],
        "supporting": [
            "natural language processing",
            "computer vision",
            "MLOps and model deployment",
            "version control with Git",
            "cloud platforms (AWS/GCP/Azure)",
            "Docker containerization",
            "SQL and database querying",
        ],
    },
    "Data Scientist": {
        "core": [
            "statistical analysis",
            "Python programming",
            "data visualization",
            "SQL and database querying",
            "machine learning fundamentals",
            "exploratory data analysis",
            "communicating insights to stakeholders",
        ],
        "supporting": [
            "A/B testing and experimentation",
            "big data tools (Spark/Hadoop)",
            "deep learning with neural networks",
            "business domain knowledge",
            "data storytelling and presentation",
            "R programming",
            "cloud platforms (AWS/GCP/Azure)",
        ],
    },
    "ML Engineer": {
        "core": [
            "machine learning fundamentals",
            "Python programming",
            "model deployment and serving",
            "MLOps and model deployment",
            "software engineering best practices",
            "version control with Git",
            "REST API development",
        ],
        "supporting": [
            "Docker containerization",
            "Kubernetes orchestration",
            "cloud platforms (AWS/GCP/Azure)",
            "CI/CD pipelines",
            "distributed systems",
            "deep learning with neural networks",
            "monitoring and logging systems",
        ],
    },
    "Cloud Engineer": {
        "core": [
            "cloud platforms (AWS/GCP/Azure)",
            "Linux system administration",
            "networking fundamentals",
            "Infrastructure as Code (Terraform/CloudFormation)",
            "Docker containerization",
            "Kubernetes orchestration",
            "CI/CD pipelines",
        ],
        "supporting": [
            "cloud security best practices",
            "scripting with Python or Bash",
            "cost optimization and monitoring",
            "version control with Git",
            "database administration",
            "disaster recovery planning",
            "microservices architecture",
        ],
    },
    "Backend Developer": {
        "core": [
            "REST API development",
            "database design and SQL",
            "server-side programming (Python/Java/Node.js)",
            "software engineering best practices",
            "version control with Git",
            "authentication and authorization",
            "debugging and testing",
        ],
        "supporting": [
            "Docker containerization",
            "cloud platforms (AWS/GCP/Azure)",
            "caching and performance optimization",
            "message queues and async processing",
            "microservices architecture",
            "CI/CD pipelines",
            "database administration",
        ],
    },
}


def list_target_roles() -> list[str]:
    """Returns the list of supported target role names, in a fixed order."""
    return list(TARGET_ROLES.keys())


def get_role_skills(role_name: str) -> dict:
    """
    Returns {"core": [...], "supporting": [...]} for a given role, or raises
    KeyError with a clear message if the role isn't in the taxonomy.
    """
    if role_name not in TARGET_ROLES:
        raise KeyError(
            f"Unknown target role '{role_name}'. Supported roles: {list_target_roles()}"
        )
    return TARGET_ROLES[role_name]


def get_all_role_skills_flat(role_name: str) -> list[str]:
    """Returns core + supporting skills for a role as one flat list, core first."""
    role = get_role_skills(role_name)
    return role["core"] + role["supporting"]
