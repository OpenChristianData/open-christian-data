import type { ArtifactDiscoveryResponse, ArtifactPage, ArtifactSummary, ComparePaneRequest, ImageRequest, CompareView, CorrespondenceSource, ImageResponseMetadata, LocationDiscovery, RecordedArtifactContext, ReviewCatalog, ReviewWork, ReviewWorkResponse, SegmentRange, SessionDescriptor, StageId, StageView } from "./types";

export const DEFAULT_REQUEST_TIMEOUT_MS = 12_000;
// Complete collection renders can exceed 30 seconds when they do not fit in
// the bounded server cache. Navigation still cancels immediately; stalled
// artifact requests retain a finite deadline.
export const ARTIFACT_REQUEST_TIMEOUT_MS = 120_000;
export const MAX_CATALOG_PAGE_SIZE = 50;
export const MAX_ARTIFACT_PAGE_SIZE = 50;

export interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  retries?: number;
}

interface ErrorResponseBody {
  error?: { code?: unknown; message?: unknown; request_id?: unknown };
  request_id?: unknown;
}

interface ReviewRequestErrorOptions {
  code?: string;
  requestId?: string | null;
  status?: number | null;
  path: string;
  retryable?: boolean;
  cause?: unknown;
}

export class ReviewRequestError extends Error {
  readonly code: string;
  readonly requestId: string | null;
  readonly status: number | null;
  readonly path: string;
  readonly retryable: boolean;

  constructor(message: string, options: ReviewRequestErrorOptions) {
    super(message, { cause: options.cause });
    this.name = "ReviewRequestError";
    this.code = options.code ?? "request-failed";
    this.requestId = options.requestId ?? null;
    this.status = options.status ?? null;
    this.path = options.path;
    this.retryable = options.retryable ?? false;
  }
}

export function isRequestAborted(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

export function artifactRequestOptions(signal: AbortSignal): RequestOptions {
  return { signal, timeoutMs: ARTIFACT_REQUEST_TIMEOUT_MS };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function responseHeader(response: Response, name: string): string | null {
  return typeof response.headers?.get === "function" ? response.headers.get(name) : null;
}

function responseErrorDetails(response: Response, body: unknown, fallbackMessage: string): { message: string; code: string; requestId: string | null } {
  const errorBody = isRecord(body) ? body as ErrorResponseBody : {};
  const nested = isRecord(errorBody.error) ? errorBody.error : {};
  const message = typeof nested.message === "string" ? nested.message : fallbackMessage;
  const code = typeof nested.code === "string" ? nested.code : "http-error";
  const bodyRequestId = typeof nested.request_id === "string"
    ? nested.request_id
    : typeof errorBody.request_id === "string" ? errorBody.request_id : null;
  return { message, code, requestId: responseHeader(response, "X-CVW-Request-ID") ?? bodyRequestId };
}

function requestTimeout(options: RequestOptions): number {
  const timeout = options.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
  return Number.isFinite(timeout) && timeout > 0 ? timeout : DEFAULT_REQUEST_TIMEOUT_MS;
}

function requestRetries(options: RequestOptions): number {
  const retries = options.retries ?? 1;
  return Number.isSafeInteger(retries) && retries >= 0 ? retries : 1;
}

async function getResponse<T>(path: string, read: (response: Response) => Promise<T>, accept: string, fallbackMessage: string, options: RequestOptions = {}): Promise<T> {
  const retryLimit = requestRetries(options);
  let attempt = 0;
  while (true) {
    const controller = new AbortController();
    let timedOut = false;
    const abortFromCaller = () => controller.abort();
    if (options.signal?.aborted) controller.abort();
    else options.signal?.addEventListener("abort", abortFromCaller, { once: true });
    const timeoutId = setTimeout(() => { timedOut = true; controller.abort(); }, requestTimeout(options));
    try {
      const response = await fetch(path, { headers: { Accept: accept }, signal: controller.signal });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as unknown;
        const details = responseErrorDetails(response, body, fallbackMessage);
        throw new ReviewRequestError(details.message, {
          code: details.code,
          requestId: details.requestId,
          status: response.status,
          path,
          retryable: false,
        });
      }
      return await read(response);
    } catch (caught) {
      if (isRequestAborted(caught)) {
        if (options.signal?.aborted) throw caught;
        throw new ReviewRequestError(
          timedOut ? "The local review service did not respond before the request timed out." : "The local review request was aborted.",
          { code: timedOut ? "timeout" : "aborted", path, retryable: timedOut, cause: caught },
        );
      }
      if (caught instanceof ReviewRequestError) throw caught;
      if (attempt < retryLimit) { attempt += 1; continue; }
      throw new ReviewRequestError(
        "The local review service could not be reached. Check the session launcher and retry.",
        { code: "network-error", path, retryable: true, cause: caught },
      );
    } finally {
      clearTimeout(timeoutId);
      options.signal?.removeEventListener("abort", abortFromCaller);
    }
  }
}

async function getJson<T>(path: string, fallbackMessage = "Artifact could not be opened.", options: RequestOptions = {}): Promise<T> {
  return getResponse(path, (response) => response.json().catch(() => null) as Promise<T>, "application/json", fallbackMessage, options);
}

export async function loadNativeImage(path: string, options: RequestOptions): Promise<{ blob: Blob; metadata: ImageResponseMetadata | null }> {
  return getResponse(path, async (response) => {
    const header = responseHeader(response, "X-CVW-Image-Metadata");
    let metadata: ImageResponseMetadata | null = null;
    if (header) {
      try { metadata = JSON.parse(header) as ImageResponseMetadata; }
      catch { throw new ReviewRequestError("Image provenance could not be read.", {code: "image-metadata-invalid", path}); }
    }
    return {blob: await response.blob(), metadata};
  }, "image/png,image/jpeg,image/webp", "The selected image could not be loaded.", options);
}

export function governedIdentityText(value: string, name: string): string {
  const scalars = Array.from(value);
  const hasSurrogate = scalars.some((item) => item.length === 1 && item.charCodeAt(0) >= 0xd800 && item.charCodeAt(0) <= 0xdfff);
  if (!value.trim() || hasSurrogate || scalars.length > 256) throw new Error(`${name} must be nonempty Unicode scalar text within its bound.`);
  return value;
}

export function governedLocationText(value: string, name: string): string {
  const scalars = Array.from(value);
  const hasSurrogate = scalars.some((item) => item.length === 1 && item.charCodeAt(0) >= 0xd800 && item.charCodeAt(0) <= 0xdfff);
  if (!value.trim() || hasSurrogate || scalars.length > 512) throw new Error(`${name} must be nonempty Unicode scalar text within its bound.`);
  return value;
}

function validateCatalogIdentities(catalog: ReviewCatalog): ReviewCatalog {
  for (const work of catalog.works) {
    for (const stage of work.stages) {
      if (!stage.selected_artifact) continue;
      governedIdentityText(stage.selected_artifact.id, `catalog ${stage.id} selected artifact id`);
      governedIdentityText(stage.selected_artifact.version, `catalog ${stage.id} selected artifact version`);
    }
    for (const stage of work.stages) {
      for (const artifact of stage.artifacts) {
        governedIdentityText(artifact.id, `catalog ${stage.id} artifact id`);
        governedIdentityText(artifact.version, `catalog ${stage.id} artifact version`);
      }
    }
    for (const source of work.correspondence_sources) {
      governedIdentityText(source.id, "catalog correspondence source id");
      governedIdentityText(source.left_artifact_id, "catalog correspondence left artifact id");
      governedIdentityText(source.left_artifact_version, "catalog correspondence left artifact version");
      governedIdentityText(source.right_artifact_id, "catalog correspondence right artifact id");
      governedIdentityText(source.right_artifact_version, "catalog correspondence right artifact version");
    }
  }
  return catalog;
}

const SHA256 = /^[a-f0-9]{64}$/;

function governedCatalogVersion(value: string, name = "catalogVersion"): string {
  if (!SHA256.test(value)) throw new Error(`${name} must be a lowercase SHA-256 digest.`);
  return value;
}

function boundedPageNumber(value: number, name: string, maximum: number): number {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error(`${name} must be a nonnegative safe integer.`);
  if (name === "limit" && (value < 1 || value > maximum)) throw new Error(`${name} must be between 1 and ${maximum}.`);
  return value;
}

function responseContractError(path: string, message: string, code = "response-invalid"): never {
  throw new ReviewRequestError(message, {code, path, status: 200, retryable: false});
}

function responseRecord(value: unknown, path: string, label: string): Record<string, unknown> {
  if (!isRecord(value)) responseContractError(path, `${label} response must be an object.`);
  return value;
}

function responseArray(value: unknown, path: string, label: string): unknown[] {
  if (!Array.isArray(value)) responseContractError(path, `${label} response must be an array.`);
  return value;
}

function responseString(value: unknown, path: string): string {
  if (typeof value !== "string") responseContractError(path, `${path} must be a string.`);
  return value;
}

function responseIdentity(value: unknown, path: string): string {
  const text = responseString(value, path);
  try {
    return governedIdentityText(text, path);
  } catch (caught) {
    responseContractError(path, `${path} is invalid: ${caught instanceof Error ? caught.message : "invalid value"}`);
  }
}

function responsePath(value: unknown, path: string): string {
  const text = responseString(value, path);
  const scalars = Array.from(text);
  const hasSurrogate = scalars.some((item) => item.length === 1 && item.charCodeAt(0) >= 0xd800 && item.charCodeAt(0) <= 0xdfff);
  if (!text.trim() || hasSurrogate) responseContractError(path, `${path} must be nonempty Unicode scalar text.`);
  return text;
}

function validateArtifactSummary(value: unknown, path: string): ArtifactSummary {
  const artifact = responseRecord(value, path, "Artifact");
  responseIdentity(artifact.id, `${path}.id`);
  responseIdentity(artifact.version, `${path}.version`);
  responseIdentity(artifact.name, `${path}.name`);
  responsePath(artifact.path, `${path}.path`);
  responseIdentity(artifact.media_type, `${path}.media_type`);
  if (!Number.isSafeInteger(artifact.bytes) || Number(artifact.bytes) < 0) responseContractError(path, `${path}.bytes must be a nonnegative safe integer.`);
  if (typeof artifact.sha256 !== "string" || !SHA256.test(artifact.sha256)) responseContractError(path, `${path}.sha256 must be a lowercase SHA-256 digest.`);
  if (artifact.approved_root_id !== undefined) responseIdentity(artifact.approved_root_id, `${path}.approved_root_id`);
  if (artifact.candidate_validation_tei_artifact_id !== undefined) responseIdentity(artifact.candidate_validation_tei_artifact_id, `${path}.candidate_validation_tei_artifact_id`);
  return artifact as unknown as ArtifactSummary;
}

function validateWorkIdentities(value: unknown, path: string): ReviewWork {
  const work = responseRecord(value, path, "Work");
  responseIdentity(work.slug, `${path}.slug`);
  const stages = responseArray(work.stages, path, "Work stages");
  const stageIds = new Set<string>();
  for (const [index, value] of stages.entries()) {
    const stagePath = `${path}.stages[${index}]`;
    const stage = responseRecord(value, stagePath, "Stage");
    const stageId = responseString(stage.id, `${stagePath}.id`);
    if (stageIds.has(stageId) || (stageId !== "source" && stageId !== "tei")) responseContractError(stagePath, `${stagePath}.id is invalid or duplicated.`);
    stageIds.add(stageId);
    const artifacts = responseArray(stage.artifacts, stagePath, "Stage artifacts").map((item, artifactIndex) => validateArtifactSummary(item, `${stagePath}.artifacts[${artifactIndex}]`));
    if (stage.selected_artifact !== null && stage.selected_artifact !== undefined) {
      const selected = responseRecord(stage.selected_artifact, `${stagePath}.selected_artifact`, "Selected artifact");
      responseIdentity(selected.id, `${stagePath}.selected_artifact.id`);
      responseIdentity(selected.version, `${stagePath}.selected_artifact.version`);
    }
    if (stage.artifact_discovery !== undefined) {
      const discovery = responseRecord(stage.artifact_discovery, `${stagePath}.artifact_discovery`, "Artifact discovery");
      if (!Number.isSafeInteger(discovery.total) || Number(discovery.total) < artifacts.length || discovery.returned !== artifacts.length || typeof discovery.complete !== "boolean") responseContractError(stagePath, `${stagePath}.artifact_discovery is inconsistent with returned artifacts.`);
    }
  }
  responseArray(work.correspondence_sources, path, "Correspondence sources");
  try {
    // Keep the existing catalog identity rules authoritative for detail and summary pages.
    return validateCatalogIdentities({works: [work]} as unknown as ReviewCatalog).works[0];
  } catch (caught) {
    responseContractError(path, `${path} contains an invalid retained identity: ${caught instanceof Error ? caught.message : "invalid value"}`);
  }
}

function validatePageMetadata(page: Record<string, unknown>, path: string, expectedOffset: number, returned: number, total: number, expectedLimit: number, expectedVersion?: string): void {
  const offset = page.offset;
  const pageReturned = page.returned;
  const pageTotal = page.total;
  if (typeof offset !== "number" || !Number.isSafeInteger(offset) || offset !== expectedOffset
    || typeof pageReturned !== "number" || !Number.isSafeInteger(pageReturned) || pageReturned !== returned || pageReturned > expectedLimit
    || typeof pageTotal !== "number" || !Number.isSafeInteger(pageTotal) || pageTotal !== total
    || offset > pageTotal || offset + pageReturned > pageTotal) responseContractError(path, `${path} metadata does not match its returned entries.`);
  if (expectedVersion !== undefined && page.catalog_version !== expectedVersion) responseContractError(path, `${path}.catalog_version does not match the response catalog version.`);
  const next = page.next_offset;
  if (next === null) {
    if (offset + pageReturned < pageTotal) responseContractError(path, `${path}.next_offset is missing while more entries remain.`);
  } else if (typeof next !== "number" || !Number.isSafeInteger(next) || next !== offset + pageReturned || next <= offset || next >= pageTotal) {
    responseContractError(path, `${path}.next_offset does not make exact forward progress within the total.`);
  }
}

function validateCatalogResponse(value: unknown, path: string, expectedOffset: number, expectedLimit: number, expectedVersion?: string): ReviewCatalog {
  const catalog = responseRecord(value, path, "Catalog");
  if (catalog.contract !== "ocd-corpus-review-catalog-v1" || catalog.manifest_contract !== "ocd-corpus-review-manifest-v1") responseContractError(path, "The catalog response contract is invalid.");
  const catalogVersion = typeof catalog.catalog_version === "string" && SHA256.test(catalog.catalog_version) ? catalog.catalog_version : responseContractError(path, "The catalog response has no valid catalog_version.");
  if (expectedVersion && catalogVersion !== expectedVersion) responseContractError(path, "The catalog page belongs to a different manifest version.", "catalog-version-drift");
  const works = responseArray(catalog.works, path, "Catalog works");
  const page = responseRecord(catalog.page, path, "Catalog page");
  if (page.catalog_version !== catalogVersion) responseContractError(path, "The catalog page catalog_version does not match the response catalog version.");
  if (!Number.isSafeInteger(page.total)) responseContractError(path, "The catalog page total is invalid.");
  validatePageMetadata(page, `${path}.page`, expectedOffset, works.length, page.total as number, expectedLimit, catalogVersion);
  responseArray(catalog.approved_roots, path, "Catalog approved roots");
  const validatedWorks = works.map((work, index) => validateWorkIdentities(work, `${path}.works[${index}]`));
  return {...catalog, works: validatedWorks} as unknown as ReviewCatalog;
}

function validateWorkResponse(value: unknown, path: string, slug: string, expectedVersion?: string, selection?: WorkSelection): ReviewWorkResponse {
  const response = responseRecord(value, path, "Work detail");
  if (response.contract !== "ocd-corpus-review-work-v1") responseContractError(path, "The work detail response contract is invalid.");
  const catalogVersion = typeof response.catalog_version === "string" && SHA256.test(response.catalog_version) ? response.catalog_version : responseContractError(path, "The work detail response has no valid catalog_version.");
  if (expectedVersion && catalogVersion !== expectedVersion) responseContractError(path, "The work detail belongs to a different manifest version.", "catalog-version-drift");
  const work = validateWorkIdentities(response.work, `${path}.work`);
  if (work.slug !== slug) responseContractError(path, "The work detail response does not match the requested work.");
  for (const [stage, artifact, version] of [["source", selection?.source_artifact, selection?.source_version], ["tei", selection?.tei_artifact, selection?.tei_version]] as const) {
    if ((artifact === undefined) !== (version === undefined)) responseContractError(path, `${stage} artifact identity is incomplete.`);
    if (artifact !== undefined) {
      const stageValue = work.stages.find((item) => item.id === stage);
      if (!stageValue?.artifacts.some((item) => item.id === artifact && item.version === version)) responseContractError(path, `The requested ${stage} artifact identity was not returned.`);
    }
  }
  return {contract: "ocd-corpus-review-work-v1", catalog_version: catalogVersion, work};
}

function validateArtifactResponse(value: unknown, path: string, expectedVersion?: string, expectedOffset = 0, expectedLimit = MAX_ARTIFACT_PAGE_SIZE): ArtifactDiscoveryResponse {
  const response = responseRecord(value, path, "Artifact discovery");
  if (response.contract !== "ocd-corpus-review-artifacts-v1") responseContractError(path, "The artifact discovery response contract is invalid.");
  const catalogVersion = typeof response.catalog_version === "string" && SHA256.test(response.catalog_version) ? response.catalog_version : responseContractError(path, "The artifact discovery response has no valid catalog_version.");
  if (expectedVersion && catalogVersion !== expectedVersion) responseContractError(path, "The artifact page belongs to a different manifest version.", "catalog-version-drift");
  const artifacts = responseArray(response.artifacts, path, "Artifact discovery entries").map((item, index) => validateArtifactSummary(item, `${path}.artifacts[${index}]`));
  const page = responseRecord(response.page, path, "Artifact page");
  if (!Number.isSafeInteger(response.matched) || !Number.isSafeInteger(response.total) || Number(response.matched) > Number(response.total)) responseContractError(path, "The artifact discovery totals are invalid.");
  validatePageMetadata(page, `${path}.page`, expectedOffset, artifacts.length, Number(response.matched), expectedLimit);
  return {contract: "ocd-corpus-review-artifacts-v1", catalog_version: catalogVersion, artifacts, page: page as unknown as ArtifactPage, matched: Number(response.matched), total: Number(response.total)};
}

export interface CatalogPageQuery { offset?: number; limit?: number; catalogVersion?: string; search?: string; state?: string }

export interface WorkSelection {
  source_artifact?: string;
  source_version?: string;
  tei_artifact?: string;
  tei_version?: string;
}

export interface ArtifactDiscoveryQuery {
  offset?: number;
  limit?: number;
  search?: string;
  catalogVersion?: string;
  artifactId?: string;
  artifactVersion?: string;
}

export async function loadReviewCatalogPage(query: CatalogPageQuery = {}, options?: RequestOptions): Promise<ReviewCatalog> {
  const offset = boundedPageNumber(query.offset ?? 0, "offset", MAX_CATALOG_PAGE_SIZE);
  const limit = boundedPageNumber(query.limit ?? MAX_CATALOG_PAGE_SIZE, "limit", MAX_CATALOG_PAGE_SIZE);
  const params = new URLSearchParams({view: "summary", offset: String(offset), limit: String(limit)});
  const catalogVersion = query.catalogVersion === undefined ? undefined : governedCatalogVersion(query.catalogVersion);
  if (catalogVersion) params.set("catalog_version", catalogVersion);
  if (query.search) params.set("search", query.search);
  if (query.state && query.state !== "all") params.set("state", query.state);
  const path = `/api/review/v1/works?${params}`;
  return validateCatalogResponse(await getJson(path, "The review library could not be loaded.", options), path, offset, limit, catalogVersion);
}


export async function loadReviewWork(slug: string, selection: WorkSelection = {}, catalogVersion?: string, options?: RequestOptions): Promise<ReviewWorkResponse> {
  const governedSlug = governedIdentityText(slug, "work slug");
  const params = new URLSearchParams();
  for (const [stage, artifact, version] of [["source", selection.source_artifact, selection.source_version], ["tei", selection.tei_artifact, selection.tei_version]] as const) {
    if ((artifact === undefined) !== (version === undefined)) throw new Error(`${stage} artifact and version must appear together.`);
  }
  for (const [name, value] of [["source_artifact", selection.source_artifact], ["source_version", selection.source_version], ["tei_artifact", selection.tei_artifact], ["tei_version", selection.tei_version]] as const) {
    if (value !== undefined) params.set(name, governedIdentityText(value, name));
  }
  const version = catalogVersion === undefined ? undefined : governedCatalogVersion(catalogVersion);
  if (version) params.set("catalog_version", version);
  const path = `/api/review/v1/works/${encodeURIComponent(governedSlug)}${params.toString() ? `?${params}` : ""}`;
  return validateWorkResponse(await getJson(path, "The requested work could not be loaded.", options), path, governedSlug, version, selection);
}

export async function loadArtifactDiscovery(slug: string, stage: StageId, query: ArtifactDiscoveryQuery = {}, options?: RequestOptions): Promise<ArtifactDiscoveryResponse> {
  const governedSlug = governedIdentityText(slug, "work slug");
  const offset = boundedPageNumber(query.offset ?? 0, "offset", MAX_ARTIFACT_PAGE_SIZE);
  const limit = boundedPageNumber(query.limit ?? MAX_ARTIFACT_PAGE_SIZE, "limit", MAX_ARTIFACT_PAGE_SIZE);
  const params = new URLSearchParams({offset: String(offset), limit: String(limit)});
  const search = query.search === undefined ? undefined : boundedLocationSearch(query.search).trim();
  if (search) params.set("search", governedIdentityText(search, "artifact search"));
  const version = query.catalogVersion === undefined ? undefined : governedCatalogVersion(query.catalogVersion);
  if (version) params.set("catalog_version", version);
  if (query.artifactId !== undefined || query.artifactVersion !== undefined) {
    if (query.artifactId === undefined || query.artifactVersion === undefined) throw new Error("artifactId and artifactVersion must appear together.");
    params.set("artifact_id", governedIdentityText(query.artifactId, "artifactId"));
    params.set("artifact_version", governedIdentityText(query.artifactVersion, "artifactVersion"));
  }
  const path = `/api/review/v1/works/${encodeURIComponent(governedSlug)}/stages/${encodeURIComponent(stage)}/artifacts?${params}`;
  return validateArtifactResponse(await getJson(path, "Artifact discovery could not be loaded.", options), path, version, offset, limit);
}

export function loadReviewSession(options?: RequestOptions): Promise<SessionDescriptor> {
  return getJson("/api/review/v1/session", "Session diagnostics could not be loaded.", options);
}

function addRange(params: URLSearchParams, prefix: string, range?: SegmentRange): void {
  if (!range) return;
  if (!Number.isSafeInteger(range.start) || range.start < 0 || !Number.isSafeInteger(range.limit) || range.limit < 1) {
    throw new Error("Segment range must contain a nonnegative integer start and positive integer limit.");
  }
  params.set(`${prefix}segment_start`, String(range.start));
  params.set(`${prefix}segment_limit`, String(range.limit));
}

export interface LocationQuery {
  offset?: number;
  limit?: number;
  search?: string;
}

export const MAX_LOCATION_SEARCH_SCALARS = 256;

export function boundedLocationSearch(value: string): string {
  return Array.from(value).slice(0, MAX_LOCATION_SEARCH_SCALARS).join("");
}

export function loadLocations(slug: string, stage: StageId, recorded: Pick<RecordedArtifactContext, "artifact_id" | "version">, query: LocationQuery = {}, options?: RequestOptions): Promise<LocationDiscovery> {
  const offset = query.offset ?? 0;
  const limit = query.limit ?? 32;
  const search = query.search === undefined ? undefined : boundedLocationSearch(query.search);
  if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isSafeInteger(limit) || limit < 1 || limit > 32) {
    throw new Error("Location range must contain a nonnegative offset and a bounded positive limit.");
  }
  const params = new URLSearchParams({
    expected_artifact: governedIdentityText(recorded.artifact_id, "artifact"),
    expected_version: governedIdentityText(recorded.version, "version"),
    offset: String(offset),
    limit: String(limit),
  });
  if (search !== undefined) params.set("search", governedIdentityText(search, "location search"));
  return getJson(`/api/review/v1/works/${encodeURIComponent(slug)}/stages/${encodeURIComponent(stage)}/locations?${params}`, "Locations could not be loaded.", options);
}

export function loadStageView(slug: string, stage: StageId, recorded: RecordedArtifactContext, from?: CorrespondenceSource, range?: SegmentRange, options?: RequestOptions, autoPage = false): Promise<StageView> {
  const params = new URLSearchParams({
    expected_artifact: governedIdentityText(recorded.artifact_id, "artifact"),
    expected_version: governedIdentityText(recorded.version, "version"),
    location: governedLocationText(recorded.location, "location"),
  });
  if (from) {
    params.set("from_stage", from.stage);
    params.set("from_location", governedLocationText(from.location, "fromLocation"));
  }
  addRange(params, "", range);
  if (autoPage) params.set("auto_page", "true");
  return getJson(`/api/review/v1/works/${encodeURIComponent(slug)}/stages/${encodeURIComponent(stage)}?${params}`, "The requested artifact could not be opened.", options);
}

export async function loadStageViewAutoPaged(slug: string, stage: StageId, recorded: RecordedArtifactContext, from?: CorrespondenceSource, range?: SegmentRange, options?: RequestOptions): Promise<StageView> {
  if (range) return loadStageView(slug, stage, recorded, from, range, options);
  const initial = await loadStageView(slug, stage, recorded, from, undefined, options, true);
  if (initial.location_state !== "page-required" || !initial.paging) return initial;
  const firstWindow = Math.min(initial.paging.max_segments_per_request, initial.paging.segment_count);
  const target = initial.paging.location_segment ?? 0;
  const start = Math.floor(target / firstWindow) * firstWindow;
  return loadStageView(slug, stage, recorded, from, {start, limit: Math.min(firstWindow, initial.paging.segment_count - start)}, options);
}

export function loadCompareView(slug: string, left: ComparePaneRequest, right: ComparePaneRequest, linked: boolean, correspondence: string | null, leftRange?: SegmentRange, rightRange?: SegmentRange, options?: RequestOptions, leftImage?: ImageRequest | null, rightImage?: ImageRequest | null, autoPage = false): Promise<CompareView> {
  const query = new URLSearchParams({
    left_stage: left.stage,
    left_artifact: governedIdentityText(left.artifact_id, "leftArtifact"),
    left_version: governedIdentityText(left.artifact_version, "leftVersion"),
    left_location: governedLocationText(left.location, "leftLocation"),
    right_stage: right.stage,
    right_artifact: governedIdentityText(right.artifact_id, "rightArtifact"),
    right_version: governedIdentityText(right.artifact_version, "rightVersion"),
    right_location: governedLocationText(right.location, "rightLocation"),
    linked: String(linked),
    correspondence: correspondence ?? "absent",
  });
  for (const [side, selection] of [["left", leftImage], ["right", rightImage]] as const) {
    if (!selection) continue;
    if (selection.variant === "region") {
      query.set(`${side}_region`, selection.region); query.set(`${side}_image_sha256`, selection.source_sha256);
    } else query.set(`${side}_image`, selection.variant);
  }
  addRange(query, "left_", leftRange);
  addRange(query, "right_", rightRange);
  if (autoPage) query.set("auto_page", "true");
  return getJson(`/api/review/v1/works/${encodeURIComponent(slug)}/compare?${query}`, "The comparison could not be opened.", options);
}

export async function loadCompareViewAutoPaged(slug: string, left: ComparePaneRequest, right: ComparePaneRequest, linked: boolean, correspondence: string | null, leftRange?: SegmentRange, rightRange?: SegmentRange, options?: RequestOptions, leftImage?: ImageRequest | null, rightImage?: ImageRequest | null): Promise<CompareView> {
  const initial = await loadCompareView(slug, left, right, linked, correspondence, leftRange, rightRange, options, leftImage, rightImage, !leftRange || !rightRange);
  const firstRange = (view: StageView): SegmentRange | undefined => view.location_state === "page-required" && view.paging
    ? {start: view.paging.location_segment ?? 0, limit: 1}
    : undefined;
  const firstLeft = leftRange ?? firstRange(initial.left);
  const firstRight = rightRange ?? firstRange(initial.right);
  if (!firstLeft && !firstRight) return initial;
  if (firstLeft === leftRange && firstRight === rightRange) return initial;
  return loadCompareView(slug, left, right, linked, correspondence, firstLeft, firstRight, options, leftImage, rightImage);
}
