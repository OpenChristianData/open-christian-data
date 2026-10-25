import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  artifactRequestOptions,
  ARTIFACT_REQUEST_TIMEOUT_MS,
  DEFAULT_REQUEST_TIMEOUT_MS,
  loadArtifactDiscovery,
  loadCompareView,
  loadCompareViewAutoPaged,
  loadReviewCatalogPage,
  loadReviewWork,
  loadStageView,
  loadStageViewAutoPaged,
} from "./api";
import type { ComparePaneRequest, RecordedArtifactContext } from "./types";

const recorded: RecordedArtifactContext = { artifact_id: "artifact", version: "v1", location: "start" };
const left: ComparePaneRequest = { stage: "source", artifact_id: "source", artifact_version: "v1", location: "start" };
const right: ComparePaneRequest = { stage: "tei", artifact_id: "tei", artifact_version: "v1", location: "start" };

function response(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response;
}

function abortError(): Error {
  return Object.assign(new Error("aborted"), { name: "AbortError" });
}

function pendingFetch(_input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return new Promise<Response>((_resolve, reject) => {
    const abort = () => reject(abortError());
    if (init?.signal?.aborted) abort();
    else init?.signal?.addEventListener("abort", abort, { once: true });
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn(pendingFetch));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("review request budgets", () => {
  it("enforces a finite artifact budget for stage and Compare requests", async () => {
    const requests = [
      () => loadStageView("work", "tei", recorded, undefined, undefined, artifactRequestOptions(new AbortController().signal)),
      () => loadCompareView("work", left, right, false, null, undefined, undefined, artifactRequestOptions(new AbortController().signal)),
    ];

    for (const request of requests) {
      const pending = request();
      const result = expect(pending).rejects.toMatchObject({ code: "timeout" });
      expect(new URL(String(vi.mocked(fetch).mock.calls[0][0]), "http://localhost").searchParams.has("auto_page")).toBe(false);
      await vi.advanceTimersByTimeAsync(ARTIFACT_REQUEST_TIMEOUT_MS - 1);
      expect(fetch).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(1);
      await result;
      vi.clearAllMocks();
      vi.stubGlobal("fetch", vi.fn(pendingFetch));
    }
  });

  it("allows a complete collection comparison to finish after the old deadline", async () => {
    const body = { contract: "ocd-corpus-review-compare-v1" };
    vi.mocked(fetch).mockImplementationOnce((_input, init) => new Promise<Response>((resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(abortError()), { once: true });
      setTimeout(() => resolve(response(body)), 45_000);
    }));
    const pending = loadCompareView("work", left, right, false, null, undefined, undefined, artifactRequestOptions(new AbortController().signal));
    const result = expect(pending).resolves.toEqual(body);
    await vi.advanceTimersByTimeAsync(45_000);
    await result;
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps the catalog on the shorter default budget", async () => {
    const pending = loadReviewCatalogPage({}, { retries: 0 });
    const result = expect(pending).rejects.toMatchObject({ code: "timeout" });
    await vi.advanceTimersByTimeAsync(DEFAULT_REQUEST_TIMEOUT_MS - 1);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await result;
  });

  it("cancels an artifact request immediately without retrying", async () => {
    const controller = new AbortController();
    const pending = loadCompareView("work", left, right, false, null, undefined, undefined, artifactRequestOptions(controller.signal));
    expect(fetch).toHaveBeenCalledTimes(1);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("retains the artifact budget for an auto-paged follow-up request", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(response({
      location_state: "page-required",
      paging: { max_segments_per_request: 1, segment_count: 2, location_segment: 1 },
    }));
    fetchMock.mockImplementationOnce(pendingFetch);
    const pending = loadStageViewAutoPaged("work", "tei", recorded, undefined, undefined, artifactRequestOptions(new AbortController().signal));
    const result = expect(pending).rejects.toMatchObject({ code: "timeout" });
    for (let index = 0; index < 5; index += 1) await Promise.resolve();
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(new URL(String(fetchMock.mock.calls[0][0]), "http://localhost").searchParams.get("auto_page")).toBe("true");
    expect(new URL(String(fetchMock.mock.calls[1][0]), "http://localhost").searchParams.get("segment_start")).toBe("1");
    await vi.advanceTimersByTimeAsync(ARTIFACT_REQUEST_TIMEOUT_MS - 1);
    await vi.advanceTimersByTimeAsync(1);
    await result;
  });

  it("loads recorded-location pages in one initial stage and Compare request", async () => {
    const page = {
      location_state: "in-range",
      paging: { max_segments_per_request: 1, segment_count: 3, segments: [{ index: 2 }], location_segment: 2 },
    };
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(response(page));
    await expect(loadStageViewAutoPaged("work", "tei", { ...recorded, location: "chapter-2" })).resolves.toEqual(page);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(new URL(String(fetchMock.mock.calls[0][0]), "http://localhost").searchParams.get("auto_page")).toBe("true");

    const compare = { left: page, right: page };
    fetchMock.mockResolvedValueOnce(response(compare));
    await expect(loadCompareViewAutoPaged("work", left, right, false, null)).resolves.toEqual(compare);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(new URL(String(fetchMock.mock.calls[1][0]), "http://localhost").searchParams.get("auto_page")).toBe("true");
  });
});

it("loads bounded summary, exact work detail, and late artifact discovery identities", async () => {
  const catalogVersion = "a".repeat(64);
  const source = (id: string, version: string) => ({
    id,
    version,
    name: id,
    path: `retained/${id}.txt`,
    bytes: 1,
    sha256: "b".repeat(64),
    media_type: "text/plain",
  });
  const summary = {
    contract: "ocd-corpus-review-catalog-v1",
    manifest_contract: "ocd-corpus-review-manifest-v1",
    catalog_version: catalogVersion,
    approved_roots: [],
    approved_roots_count: 58675,
    approved_roots_discovery: {route: "/api/review/v1/roots", total: 58675, page_size: 50, catalog_version: catalogVersion},
    works: [{
      slug: "church-fathers-quotations",
      title: "Church Fathers Quotations",
      creator: "Anonymous",
      scope: "work",
      candidate_validation: null,
      candidate_validations: [{
        status: "pass",
        report_sha256: "c".repeat(64),
        candidate_sha256: "d".repeat(64),
        source_manifest_sha256: "e".repeat(64),
        source_id: "large-source",
        source_artifact_ids: [],
        source_artifact_count: 58675,
        source_artifact_discovery: {total: 58675, route: "/api/review/v1/works/church-fathers-quotations/stages/source/artifacts", complete: false},
        tei_artifact_id: "tei-large",
      }],
      default_compare: null,
      stages: [
        {id: "source", label: "Retained source", availability: "available", selected_artifact: {id: "source-58674", version: "version-58674"}, artifacts: [], artifact_discovery: {total: 58675, returned: 0, complete: false}, outline: [], message: "Available"},
        {id: "tei", label: "Faithful TEI candidate", availability: "available", selected_artifact: {id: "tei-large", version: "tei-version"}, artifacts: [], artifact_discovery: {total: 1, returned: 0, complete: false}, outline: [], message: "Available"},
      ],
      correspondence_sources: [],
    }],
    page: {offset: 50, returned: 1, total: 402, next_offset: 51, catalog_version: catalogVersion},
  };
  const detail = {
    contract: "ocd-corpus-review-work-v1",
    catalog_version: catalogVersion,
    work: {
      ...summary.works[0],
      stages: [
        {...summary.works[0].stages[0], artifacts: [source("source-0", "version-0"), source("source-58674", "version-58674")], artifact_discovery: {total: 58675, returned: 2, complete: false}},
        {...summary.works[0].stages[1], artifacts: [source("tei-large", "tei-version")], artifact_discovery: {total: 1, returned: 1, complete: true}},
      ],
    },
  };
  const discovery = {
    contract: "ocd-corpus-review-artifacts-v1",
    catalog_version: catalogVersion,
    artifacts: [source("source-58674", "version-58674")],
    page: {offset: 0, returned: 1, total: 1, next_offset: null},
    matched: 1,
    total: 58675,
  };
  vi.mocked(fetch)
    .mockResolvedValueOnce(response(summary))
    .mockResolvedValueOnce(response(detail))
    .mockResolvedValueOnce(response(discovery));

  const page = await loadReviewCatalogPage({offset: 50, limit: 50, catalogVersion});
  const work = await loadReviewWork("church-fathers-quotations", {
    source_artifact: "source-58674",
    source_version: "version-58674",
    tei_artifact: "tei-large",
    tei_version: "tei-version",
  }, catalogVersion);
  const late = await loadArtifactDiscovery("church-fathers-quotations", "source", {
    offset: 0,
    limit: 50,
    search: "58674",
    catalogVersion,
  });

  expect(new URL(String(vi.mocked(fetch).mock.calls[0][0]), "http://localhost").search).toContain("view=summary");
  expect(page.page.next_offset).toBe(51);
  expect(work.work.stages.find((stage) => stage.id === "source")?.artifacts.some((item) => item.id === "source-58674" && item.version === "version-58674")).toBe(true);
  expect(late.artifacts[0]).toMatchObject({id: "source-58674", version: "version-58674"});
});

it("keeps artifact path semantics distinct from bounded identities and rejects malformed cursors", async () => {
  const catalogVersion = "a".repeat(64);
  await expect(loadReviewWork("church-fathers-quotations", {source_artifact: "source-only"}, catalogVersion)).rejects.toThrow("source artifact and version must appear together");
  const longPathArtifact = {
    id: "source-long-path",
    version: "version-1",
    name: "source.txt",
    path: `retained/${"nested/".repeat(50)}source.txt`,
    bytes: 1,
    sha256: "b".repeat(64),
    media_type: "text/plain",
  };
  const fetchMock = vi.mocked(fetch);
  fetchMock.mockResolvedValueOnce(response({
    contract: "ocd-corpus-review-artifacts-v1",
    catalog_version: catalogVersion,
    artifacts: [longPathArtifact],
    page: {offset: 0, returned: 1, total: 1, next_offset: null},
    matched: 1,
    total: 1,
  }));
  await expect(loadArtifactDiscovery("church-fathers-quotations", "source", {catalogVersion})).resolves.toMatchObject({artifacts: [longPathArtifact]});

  fetchMock.mockResolvedValueOnce(response({
    contract: "ocd-corpus-review-artifacts-v1",
    catalog_version: catalogVersion,
    artifacts: [{...longPathArtifact, id: 7}],
    page: {offset: 0, returned: 1, total: 1, next_offset: null},
    matched: 1,
    total: 1,
  }));
  await expect(loadArtifactDiscovery("church-fathers-quotations", "source", {catalogVersion})).rejects.toMatchObject({code: "response-invalid"});

  fetchMock.mockResolvedValueOnce(response({
    contract: "ocd-corpus-review-artifacts-v1",
    catalog_version: catalogVersion,
    artifacts: [longPathArtifact],
    page: {offset: 0, returned: 1, total: 2, next_offset: 1},
    matched: 1,
    total: 1,
  }));
  await expect(loadArtifactDiscovery("church-fathers-quotations", "source", {catalogVersion})).rejects.toMatchObject({code: "response-invalid"});

  fetchMock.mockResolvedValueOnce(response({
    contract: "ocd-corpus-review-artifacts-v1",
    catalog_version: catalogVersion,
    artifacts: [longPathArtifact],
    page: {offset: 0, returned: 1, total: 1, next_offset: 1},
    matched: 1,
    total: 1,
  }));
  await expect(loadArtifactDiscovery("church-fathers-quotations", "source", {catalogVersion})).rejects.toMatchObject({code: "response-invalid"});
});
