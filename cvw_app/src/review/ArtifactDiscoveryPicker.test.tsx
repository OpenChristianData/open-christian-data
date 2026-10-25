import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ArtifactDiscoveryPicker } from "./ArtifactDiscoveryPicker";
import type { ArtifactSummary } from "./types";

const catalogVersion = "a".repeat(64);

function artifact(id: string, version = "v1"): ArtifactSummary {
  return {
    id,
    version,
    name: `${id}.txt`,
    path: `retained/${id}.txt`,
    bytes: 1,
    sha256: "b".repeat(64),
    media_type: "text/plain",
  };
}

function response(body: unknown): Response {
  return {ok: true, status: 200, json: async () => body} as Response;
}

function page(items: ArtifactSummary[], offset = 0, total = 58675, matched = total) {
  return {
    contract: "ocd-corpus-review-artifacts-v1",
    catalog_version: catalogVersion,
    artifacts: items,
    page: {offset, returned: items.length, total: matched, next_offset: offset + items.length < matched ? offset + items.length : null},
    matched,
    total,
  };
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => response(page(Array.from({length: 50}, (_, index) => artifact(`source-${index}`))))));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ArtifactDiscoveryPicker", () => {
  it("keeps a late selected identity visible without rendering the full inventory", async () => {
    const selected = artifact("source-58674", "version-58674");
    const onSelect = vi.fn();
    render(<ArtifactDiscoveryPicker
      workSlug="church-fathers-quotations"
      stage="source"
      catalogVersion={catalogVersion}
      artifacts={[artifact("source-0"), selected]}
      selectedId={selected.id}
      selectedVersion={selected.version}
      total={58675}
      onSelect={onSelect}
      label="Retained source authority"
    />);

    const select = await screen.findByRole("combobox", {name: "Retained source authority"});
    await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(51));
    expect(screen.getByRole("option", {name: /source-58674\.txt/})).toBeInTheDocument();
    expect(screen.getByText(/Showing 51 of 58,675 files/)).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls[0][0]).toContain("limit=50");

    fireEvent.change(select, {target: {value: `${selected.id}\u0000${selected.version}`}});
    expect(onSelect).toHaveBeenCalledWith(selected);
  });

  it("aborts and ignores an older search response", async () => {
    let resolveFirst!: (value: Response) => void;
    let resolveSecond!: (value: Response) => void;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((resolve, reject) => {
      const abort = () => reject(Object.assign(new Error("aborted"), {name: "AbortError"}));
      if (init?.signal?.aborted) abort();
      else init?.signal?.addEventListener("abort", abort, {once: true});
      if (String(input).includes("search=late")) resolveSecond = resolve;
      else resolveFirst = resolve;
    }));
    vi.stubGlobal("fetch", fetchMock);
    const selected = artifact("source-selected", "selected-version");
    render(<ArtifactDiscoveryPicker
      workSlug="church-fathers-quotations"
      stage="source"
      catalogVersion={catalogVersion}
      artifacts={[selected]}
      selectedId={selected.id}
      selectedVersion={selected.version}
      total={58675}
      onSelect={vi.fn()}
      label="Retained source authority"
    />);

    const search = screen.getByRole("searchbox");
    fireEvent.change(search, {target: {value: "late"}});
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    resolveSecond(response(page([artifact("source-late")], 0, 1, 1)));
    await waitFor(() => expect(screen.getByRole("option", {name: /source-late\.txt/})).toBeInTheDocument());
    expect(screen.queryByRole("option", {name: /source-older\.txt/})).not.toBeInTheDocument();

    resolveFirst(response(page([artifact("source-older")])));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole("option", {name: /source-older\.txt/})).not.toBeInTheDocument();
  });

  it("filters a complete small inventory locally", async () => {
    const first = artifact("source-first");
    const match = artifact("source-matching");
    render(<ArtifactDiscoveryPicker
      workSlug="small-work"
      stage="source"
      catalogVersion={catalogVersion}
      artifacts={[first, match]}
      selectedId={first.id}
      total={2}
      onSelect={vi.fn()}
      label="Retained source authority"
    />);

    fireEvent.change(screen.getByRole("searchbox"), {target: {value: "matching"}});
    const select = screen.getByRole("combobox", {name: "Retained source authority"});
    expect(select.querySelectorAll("option")).toHaveLength(2);
    expect(screen.getByRole("option", {name: /source-matching\.txt/})).toBeInTheDocument();
  });

  it("does not substitute another version when an explicit selection version is absent", () => {
    const v1 = artifact("source-same", "v1");
    const v2 = artifact("source-same", "v2");
    render(<ArtifactDiscoveryPicker
      workSlug="small-work"
      stage="source"
      catalogVersion={catalogVersion}
      artifacts={[v1, v2]}
      selectedId={v1.id}
      selectedVersion="missing-version"
      total={2}
      onSelect={vi.fn()}
      label="Retained source authority"
    />);

    expect(screen.getByRole("combobox", {name: "Retained source authority"})).toHaveValue("");
    expect(screen.getByRole("option", {name: "Choose a file"})).toBeInTheDocument();
  });
});
