/**
 * TypeScript types for open-christian-data schemas.
 * Derived from schemas/v1/*.schema.json — JSON Schema is the source of truth.
 * Version: 1.0.0
 */

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

export type Tradition =
  | "reformed" | "lutheran" | "anglican" | "baptist" | "methodist"
  | "catholic" | "orthodox" | "ecumenical" | "non-denominational"
  | "puritan" | "nonconformist" | "patristic" | "wesleyan";

export type License = "cc0-1.0" | "cc-by-4.0" | "cc-by-sa-4.0" | "public-domain";

export type ProcessingMethod =
  | "manual" | "automated" | "automated-with-review" | "ocr" | "ocr-with-review";

export type Completeness = "full" | "partial" | "in-progress";

export interface Provenance {
  source_url: string;
  source_format: string;
  source_edition: string;
  /** ISO 8601 date: YYYY-MM-DD */
  download_date: string;
  /** sha256:{64 hex chars} */
  source_hash: string;
  processing_method: ProcessingMethod;
  processing_script_version: string;
  /** ISO 8601 date: YYYY-MM-DD */
  processing_date: string;
  notes: string | null;
}

export interface SummaryMetadata {
  generation_model: string;
  /** ISO 8601 date: YYYY-MM-DD */
  generation_date: string;
  prompt_version: string;
}

export interface ResourceMeta {
  id: string;
  title: string;
  author: string;
  author_birth_year: number | null;
  author_death_year: number | null;
  contributors: string[];
  original_publication_year: number | null;
  /** ISO 639-1 or 639-3 language code */
  language: string;
  tradition: Tradition[];
  tradition_notes: string | null;
  license: License;
  schema_type: string;
  /** Semver: major.minor.patch */
  schema_version: string;
  verse_text_source: string;
  verse_reference_standard: "OSIS";
  completeness: Completeness;
  provenance: Provenance;
  summary_metadata: SummaryMetadata | null;
}

// ---------------------------------------------------------------------------
// Commentary schema
// ---------------------------------------------------------------------------

export type SummaryReviewStatus =
  | "withheld"
  | "ai-generated-unreviewed"
  | "ai-generated-spot-checked"
  | "ai-generated-seminary-reviewed"
  | "human-written";

export interface SummaryReviewer {
  reviewer_id: string;
  credentials: string;
  /** ISO 8601 date: YYYY-MM-DD */
  review_date: string;
  review_notes: string | null;
}

export interface CommentaryEntry {
  /** Stable unique identifier: {resource-id}.{book_osis}.{chapter}.{verse_range} */
  entry_id: string;
  /** Full English book name */
  book: string;
  /** OSIS book code, e.g. "Ezek" */
  book_osis: string;
  /** Canonical Bible book order: 1 (Genesis) through 66 (Revelation) */
  book_number: number;
  chapter: number;
  /** e.g. "1", "1-3", "26-28" */
  verse_range: string;
  /** e.g. "Ezek.1.1", "Ezek.1.1-Ezek.1.3" */
  verse_range_osis: string;
  /** BSB verse text for the range, space-joined */
  verse_text: string | null;
  commentary_text: string;
  summary: string | null;
  summary_review_status: SummaryReviewStatus;
  summary_source_span: string | null;
  summary_reviewer: SummaryReviewer | null;
  key_quote: string | null;
  key_quote_source_span: string | null;
  key_quote_selection_criteria: string | null;
  /** OSIS format: e.g. "Jer.29.1", "Dan.1.1-Dan.1.6" */
  cross_references: string[];
  word_count: number;
}

export interface CommentaryMeta extends ResourceMeta {
  schema_type: "commentary";
}

export interface CommentaryResource {
  meta: CommentaryMeta;
  data: CommentaryEntry[];
}
