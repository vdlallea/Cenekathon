import pandas as pd
import numpy as np

# 1. Maak nepdata aan die exact het contract volgt
data = {
    "vacancy_id": ["vac_001", "vac_002", "vac_003", "vac_004"],
    "has_ai": [True, True, False, True],
    "ai_type": ["builder", "user", "none", "governor"],
    "confidence": [0.95, 0.88, 0.99, 0.75],
    "source": ["keyword", "keyword", "keyword", "keyword"]
}
df = pd.DataFrame(data)

# 2. Forceer de juiste data types zoals beschreven in SPEC.md
df["vacancy_id"] = df["vacancy_id"].astype(str)
df["has_ai"] = df["has_ai"].astype(bool)
df["ai_type"] = df["ai_type"].astype(str)
df["confidence"] = df["confidence"].astype(float)
df["source"] = df["source"].astype(str)

# 3. Opslaan als Parquet bestand. 
# (Let op: check of common/paths.py al bestaat voor het exacte pad. 
# Voor nu slaan we het lokaal op of in de afgesproken /data/work/ map)
output_path = "../data/work/tags.parquet" # Pas dit aan o.b.v. common/paths.py als die er is
df.to_parquet(output_path)

print(f"Stub succesvol opgeslagen op {output_path}")
