export type StageId = "source" | "tei";
export type Availability = "available" | "unavailable" | "unsupported" | "selection-required";

export interface CorrespondenceSource { stage: StageId; location: string }
export interface RecordedArtifactContext { artifact_id: string; version: string; location: string }
export interface OutlineItem { location: string; label: string; level: number }
export interface ArtifactSummary {
  id: string;
  version: string;
  name: string;
  path: string;
  bytes: number;
  sha256: string;
  media_type: string;
  approved_root_id?: string;
  candidate_validation_tei_artifact_id?: string;
}

export interface ArtifactDiscoveryMetadata {
  total: number;
  returned: number;
  complete: boolean;
}

export interface StageSummary {
  id: StageId;
  label: string;
  availability: Availability;
  selected_artifact: { id: string; version: string } | null;
  artifacts: ArtifactSummary[];
  artifact_discovery?: ArtifactDiscoveryMetadata;
  outline: OutlineItem[];
  message: string;
}

export interface CorrespondenceSummary {
  id: string;
  state: "known" | "uncertain";
  left_stage: StageId;
  left_artifact_id: string;
  left_artifact_version: string;
  right_stage: StageId;
  right_artifact_id: string;
  right_artifact_version: string;
  mappings: Array<{ left_location: string; right_location: string }>;
  mapping_count?: number;
  mapping_discovery?: { total: number; route: string; complete: boolean };
}

export interface CandidateValidationSummary {
  status: "pass";
  report_sha256: string;
  candidate_sha256: string;
  source_manifest_sha256: string;
}

export interface CandidateValidationMember extends CandidateValidationSummary {
  source_id: string;
  source_artifact_ids: string[];
  tei_artifact_id: string;
  source_artifact_count?: number;
  source_artifact_discovery?: { total: number; route: string; complete: boolean };
}

export interface ReviewWork {
  slug: string;
  title: string;
  creator: string;
  scope: string;
  candidate_validation: CandidateValidationSummary | null;
  candidate_validations?: CandidateValidationMember[];
  stages: StageSummary[];
  correspondence_sources: CorrespondenceSummary[];
  approved_roots_count?: number;
  approved_roots_discovery?: { route: string; total: number; page_size: number; catalog_version: string };
}

export interface CatalogPage {
  offset: number;
  returned: number;
  total: number;
  next_offset: number | null;
  catalog_version: string;
}

export interface ArtifactPage {
  offset: number;
  returned: number;
  total: number;
  next_offset: number | null;
}

export interface ReviewCatalog {
  contract: "ocd-corpus-review-catalog-v1";
  manifest_contract: "ocd-corpus-review-manifest-v1";
  catalog_version: string;
  approved_roots: Array<{ id: string; access: "read-only"; purpose: string }>;
  approved_roots_count?: number;
  approved_roots_discovery?: { route: string; total: number; page_size: number; catalog_version: string };
  works: ReviewWork[];
  page: CatalogPage;
}

export interface ReviewWorkResponse {
  contract: "ocd-corpus-review-work-v1";
  catalog_version: string;
  work: ReviewWork;
}

export interface ArtifactDiscoveryResponse {
  contract: "ocd-corpus-review-artifacts-v1";
  catalog_version: string;
  artifacts: ArtifactSummary[];
  page: ArtifactPage;
  matched: number;
  total: number;
}

export type SessionState = "starting" | "preflighted" | "bound" | "ready" | "stopping" | "stopped" | "failed" | "shutdown-timeout";

export interface SessionDescriptor {
  contract: "ocd-corpus-review-session-v1";
  session: {
    session_id: string;
    host: string;
    requested_port: number;
    port: number | null;
    origin: string | null;
    pid: number;
    state: SessionState;
    catalog_sha256: string | null;
    candidate_sha256: string[];
    implementation_sha256: string | null;
    preflight_elapsed_ms?: number;
    failed_phase?: string;
    error_code?: string;
    error_message?: string;
  };
}

export type DeclaredPresentationKind =
  | "sanitized-html"
  | "xml-reader"
  | "tei-reader"
  | "json-tree"
  | "exact-text"
  | "image-facsimile"
  | "pdf-native"
  | "epub-reader"
  | "barnes-zcom-reader";

export interface DocumentNode {
  type: "heading" | "paragraph" | "preformatted" | "blockquote" | "details" | "list-item" | "list" | "table" | "table-row" | "table-header" | "table-cell" | "json-object" | "json-array" | "json-property" | "json-value" | "image";
  text: string;
  level?: number;
  location?: string;
  key?: string;
  value_kind?: "string" | "number" | "boolean" | "null";
  scope?: "row" | "col";
  colspan?: number;
  rowspan?: number;
  children?: DocumentNode[];
  ordered?: boolean;
  start?: number;
  align?: "center";
  inline?: Array<{text: string; marks: string[]}>;
}

export interface ImageDimensions { width: number; height: number }
export type ImageVariant = "preview" | "original" | "region";
export type ImageRequest = { variant: "preview" | "original" } | { variant: "region"; region: string; source_sha256: string };
export interface NativeImageInfo {
  original_dimensions?: ImageDimensions;
  normalized_dimensions?: ImageDimensions;
  orientation?: { exif: number; coordinate_space: string; raw_to_normalized: number[] };
  preview?: ImageDimensions & { variant: "preview"; media_type: string; transform_version: string };
  error?: { code: string; message: string };
}
export interface ImageResponseMetadata extends NativeImageInfo {
  variant: "preview" | "region";
  region?: number[];
  source: { id: string; version: string; sha256: string; work: string; stage: string; member: { root: string; path: string }; bytes: number };
  output: ImageDimensions & { media_type: string; sha256: string; bytes: number };
  transform: { version: string; [key: string]: unknown };
}

export interface PagingDescriptor {
  mode: "segments" | "whole";
  max_segments_per_request: number;
  segment_count: number;
  segments: Array<{ index: number; scalar_count: number; locations: string[]; oversize?: boolean; truncated?: boolean }>;
  location_segment?: number | null;
  bound: { artifact_id: string; version: string; sha256: string };
  cache_resident: boolean;
}

export interface SegmentRange {
  start: number;
  limit: number;
}

export interface OutlineMetadata {
  available: boolean;
  total: number;
  returned: number;
  truncated: boolean;
  complete: boolean;
}

export interface LocationDiscovery {
  contract: "ocd-corpus-review-locations-v1";
  work: { slug: string; title: string; creator: string };
  stage: { id: StageId; label: string };
  availability: Availability;
  message: string;
  artifact: { id: string; version: string; sha256: string } | null;
  search: string | null;
  offset: number;
  limit: number;
  total: number;
  matched: number;
  returned: number;
  next_offset: number | null;
  complete: boolean;
  locations: OutlineItem[];
}

export type LocationState = "page-required" | "in-range" | "location-outside-range";
export interface CapabilityDeclaration { available: boolean; reason: string }

export interface StageView {
  image_selection?: ImageRequest;
  contract: "ocd-corpus-review-stage-view-v1";
  work: { slug: string; title: string; creator: string };
  stage: { id: StageId; label: string };
  availability: Availability;
  message: string;
  artifact: { id: string; version: string; sha256: string; media_type: string } | null;
  presentation: {
    declared_kind: DeclaredPresentationKind;
    kind: string;
    render_target: "in-browser";
    text_encoding?: string | null;
    freshness?: "admitted-snapshot" | "verified-this-request";
    limitations?: string[];
    document: { nodes: DocumentNode[] };
    original_dimensions?: ImageDimensions | null;
    native_image?: NativeImageInfo | null;
    media_presentations?: {artifact_id: string; artifact_version: string; sha256: string; caption: string; qualification: string}[];
  } | null;
  exact_fallback: { kind: "exact-text" | "exact-bytes"; target: string; label: string } | null;
  native_open: { allowed: boolean; target: string | null; reason: string };
  outline: OutlineItem[];
  outline_metadata: OutlineMetadata;
  selected_context: { location: string; label: string; text: string; document: { nodes: DocumentNode[] } } | null;
  location: { kind: string; value: string; label: string } | null;
  recorded_context: {
    state: "exact" | "drift" | "unavailable" | "location-missing";
    requested: RecordedArtifactContext | null;
    message: string;
  };
  correspondence: {
    state: "absent" | "known" | "uncertain";
    authority: string | null;
    requested_from?: CorrespondenceSource | null;
    target_location?: { kind: string; value: string; label: string } | null;
    message: string;
  };
  paging?: PagingDescriptor;
  location_state?: LocationState;
  location_message?: string;
  capabilities?: { read: CapabilityDeclaration; compare: CapabilityDeclaration };
}

export interface ComparePaneRequest {
  stage: StageId;
  artifact_id: string;
  artifact_version: string;
  location: string;
}

export interface CompareView {
  route_digest?: string;
  contract: "ocd-corpus-review-compare-view-v1";
  work: StageView["work"];
  left: StageView;
  right: StageView;
  requested_linked_navigation: boolean;
  linked_navigation: boolean;
  link_refusal: string | null;
  correspondence: {
    state: "absent" | "known" | "uncertain";
    source: string | null;
    left_stage: StageId;
    right_stage: StageId;
    left_location: string;
    right_location: string | null;
    message: string;
  };
}
