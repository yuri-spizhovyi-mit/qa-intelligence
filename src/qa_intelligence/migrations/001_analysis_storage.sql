CREATE TABLE analyses (
    analysis_id UUID PRIMARY KEY,
    request_json JSONB NOT NULL,
    draft_json JSONB NOT NULL
);

CREATE TABLE reviews (
    sequence BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    review_id UUID NOT NULL UNIQUE,
    analysis_id UUID NOT NULL REFERENCES analyses(analysis_id),
    review_json JSONB NOT NULL
);

CREATE INDEX reviews_analysis_sequence ON reviews (analysis_id, sequence);
