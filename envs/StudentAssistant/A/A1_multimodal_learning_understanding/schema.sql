PRAGMA foreign_keys = ON;

CREATE TABLE sources (
  source_id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL CHECK (
    source_type IN (
      'official_exam', 'official_answer', 'textbook',
      'third_party_solution', 'synthetic_fixture', 'web_image', 'unknown'
    )
  ),
  title TEXT,
  exam_type TEXT CHECK (
    exam_type IS NULL OR exam_type IN (
      'college_entrance_exam', 'high_school_entrance_exam',
      'postgraduate_entrance_exam', 'school_exam', 'competition', 'other'
    )
  ),
  year TEXT,
  year_status TEXT NOT NULL DEFAULT 'known' CHECK (
    year_status IN ('known', 'estimated', 'unknown')
  ),
  region TEXT,
  paper_variant TEXT,
  publisher TEXT,
  snapshot_path TEXT NOT NULL DEFAULT '',
  content_hash TEXT NOT NULL DEFAULT '',
  license TEXT,
  verification_status TEXT NOT NULL DEFAULT 'unverified' CHECK (
    verification_status IN (
      'unverified', 'pending', 'partially_verified', 'verified', 'rejected'
    )
  ),
  notes TEXT
);

CREATE TABLE artifacts (
  artifact_id TEXT PRIMARY KEY,
  user_id TEXT,
  source_id TEXT REFERENCES sources(source_id),
  file_name TEXT NOT NULL,
  media_type TEXT NOT NULL CHECK (
    media_type IN ('image', 'pdf', 'audio', 'video', 'text')
  ),
  storage_path TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  size_bytes INTEGER,
  width INTEGER,
  height INTEGER,
  status TEXT NOT NULL DEFAULT 'uploaded' CHECK (
    status IN ('uploaded', 'processed', 'verified', 'rejected')
  ),
  UNIQUE(user_id, content_hash)
);

CREATE TABLE artifact_regions (
  region_id TEXT PRIMARY KEY,
  artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
  region_index INTEGER NOT NULL CHECK (region_index > 0),
  region_type TEXT NOT NULL CHECK (
    region_type IN ('question', 'solution', 'diagram', 'text', 'unknown')
  ),
  bbox_json TEXT,
  bbox_status TEXT NOT NULL DEFAULT 'not_annotated' CHECK (
    bbox_status IN ('annotated', 'not_annotated', 'uncertain')
  ),
  confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
  status TEXT NOT NULL DEFAULT 'detected' CHECK (
    status IN ('detected', 'confirmed', 'rejected')
  ),
  UNIQUE(artifact_id, region_index)
);

CREATE TABLE recognition_runs (
  recognition_id TEXT PRIMARY KEY,
  region_id TEXT NOT NULL REFERENCES artifact_regions(region_id) ON DELETE CASCADE,
  modality TEXT NOT NULL CHECK (
    modality IN ('ocr', 'formula', 'layout', 'vision', 'other')
  ),
  engine TEXT NOT NULL,
  raw_output TEXT NOT NULL,
  normalized_output TEXT,
  confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
  status TEXT NOT NULL CHECK (
    status IN ('completed', 'failed', 'pending', 'superseded')
  )
);

CREATE TABLE recognition_corrections (
  correction_id TEXT PRIMARY KEY,
  recognition_id TEXT NOT NULL REFERENCES recognition_runs(recognition_id)
    ON DELETE CASCADE,
  old_value TEXT,
  new_value TEXT NOT NULL,
  corrected_by TEXT NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE problems (
  problem_id TEXT PRIMARY KEY,
  object_type TEXT NOT NULL DEFAULT 'question',
  subject TEXT NOT NULL,
  grade_band TEXT,
  statement TEXT NOT NULL,
  latex TEXT,
  topic TEXT,
  question_type TEXT NOT NULL CHECK (
    question_type IN (
      'multiple_choice', 'multiple_select', 'fill_blank',
      'constructed_response', 'proof', 'calculation',
      'proof_and_calculation', 'application', 'other'
    )
  ),
  has_diagram INTEGER CHECK (has_diagram IN (0, 1)),
  requires_confirmation INTEGER NOT NULL DEFAULT 0 CHECK (
    requires_confirmation IN (0, 1)
  ),
  source_id TEXT REFERENCES sources(source_id),
  exam_type TEXT,
  year TEXT,
  year_status TEXT NOT NULL DEFAULT 'known' CHECK (
    year_status IN ('known', 'estimated', 'unknown')
  ),
  region TEXT,
  paper_variant TEXT,
  question_no TEXT,
  annotation_status TEXT NOT NULL DEFAULT 'pending' CHECK (
    annotation_status IN ('draft', 'verified', 'rejected')
  ),
  notes TEXT
);

-- One row represents the expected content of one annotated image region.
CREATE TABLE recognition_ground_truth (
  ground_truth_id TEXT PRIMARY KEY,
  artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
  region_id TEXT NOT NULL REFERENCES artifact_regions(region_id) ON DELETE CASCADE,
  problem_id TEXT REFERENCES problems(problem_id),
  ground_truth_version TEXT NOT NULL DEFAULT '1.0',
  ground_truth_path TEXT NOT NULL,
  expected_region_count INTEGER NOT NULL CHECK (expected_region_count > 0),
  statement TEXT,
  latex TEXT,
  question_no TEXT,
  subject TEXT,
  grade_band TEXT,
  exam_type TEXT,
  year TEXT,
  region TEXT,
  paper_variant TEXT,
  topic TEXT,
  question_type TEXT,
  has_diagram INTEGER CHECK (has_diagram IN (0, 1)),
  requires_confirmation INTEGER NOT NULL DEFAULT 0 CHECK (
    requires_confirmation IN (0, 1)
  ),
  annotation_status TEXT NOT NULL DEFAULT 'pending' CHECK (
    annotation_status IN ('draft', 'verified', 'rejected')
  ),
  notes TEXT,
  UNIQUE(region_id)
);

CREATE TABLE learning_objects (
  object_id TEXT PRIMARY KEY,
  artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
  region_id TEXT REFERENCES artifact_regions(region_id),
  object_type TEXT NOT NULL,
  subject TEXT,
  grade_band TEXT,
  statement TEXT,
  confirmation_status TEXT NOT NULL DEFAULT 'pending' CHECK (
    confirmation_status IN ('pending', 'confirmed', 'rejected')
  )
);

CREATE TABLE problem_occurrences (
  occurrence_id TEXT PRIMARY KEY,
  problem_id TEXT NOT NULL REFERENCES problems(problem_id) ON DELETE CASCADE,
  artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
  region_id TEXT NOT NULL REFERENCES artifact_regions(region_id) ON DELETE CASCADE,
  question_no TEXT,
  ground_truth_path TEXT,
  occurrence_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (
    occurrence_status IN ('candidate', 'confirmed', 'rejected')
  ),
  UNIQUE(problem_id, artifact_id, region_id),
  UNIQUE(region_id)
);

CREATE TABLE solutions (
  solution_id TEXT PRIMARY KEY,
  problem_id TEXT NOT NULL REFERENCES problems(problem_id) ON DELETE CASCADE,
  final_answer_json TEXT NOT NULL CHECK (json_valid(final_answer_json)),
  solution_source TEXT NOT NULL,
  source_id TEXT REFERENCES sources(source_id),
  verification_status TEXT NOT NULL CHECK (
    verification_status IN (
      'unverified', 'pending_authoritative_verification',
      'independently_verified', 'third_party_verified', 'rejected'
    )
  ),
  verification_method TEXT,
  notes TEXT,
  UNIQUE(problem_id)
);

CREATE TABLE solution_steps (
  solution_id TEXT NOT NULL REFERENCES solutions(solution_id) ON DELETE CASCADE,
  step_no INTEGER NOT NULL CHECK (step_no > 0),
  text TEXT NOT NULL,
  expression TEXT,
  justification TEXT,
  is_key_step INTEGER NOT NULL DEFAULT 0 CHECK (is_key_step IN (0, 1)),
  PRIMARY KEY (solution_id, step_no)
);

CREATE TABLE solution_knowledge_points (
  solution_id TEXT NOT NULL REFERENCES solutions(solution_id) ON DELETE CASCADE,
  knowledge_point TEXT NOT NULL,
  PRIMARY KEY (solution_id, knowledge_point)
);

CREATE TABLE object_matches (
  match_id TEXT PRIMARY KEY,
  object_id TEXT NOT NULL REFERENCES learning_objects(object_id) ON DELETE CASCADE,
  problem_id TEXT REFERENCES problems(problem_id) ON DELETE CASCADE,
  match_type TEXT NOT NULL CHECK (
    match_type IN ('exact', 'similar', 'none')
  ),
  similarity_score REAL CHECK (
    similarity_score IS NULL OR similarity_score BETWEEN 0 AND 1
  ),
  status TEXT NOT NULL DEFAULT 'candidate' CHECK (
    status IN ('candidate', 'confirmed', 'rejected')
  )
);

CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event TEXT NOT NULL,
  entity_id TEXT,
  detail TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_artifacts_source ON artifacts(source_id);
CREATE INDEX idx_regions_artifact ON artifact_regions(artifact_id, region_index);
CREATE INDEX idx_ground_truth_problem ON recognition_ground_truth(problem_id);
CREATE INDEX idx_learning_objects_region ON learning_objects(region_id);
CREATE INDEX idx_problems_topic ON problems(topic);
CREATE INDEX idx_problems_exam ON problems(exam_type, year, region);
CREATE INDEX idx_occurrences_artifact ON problem_occurrences(artifact_id);
CREATE INDEX idx_occurrences_problem ON problem_occurrences(problem_id);
CREATE INDEX idx_solutions_verification ON solutions(verification_status);
CREATE INDEX idx_matches_problem ON object_matches(problem_id);
