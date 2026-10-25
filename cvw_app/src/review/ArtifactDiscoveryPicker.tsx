import { useEffect, useMemo, useRef, useState } from "react";
import { artifactRequestOptions, boundedLocationSearch, isRequestAborted, loadArtifactDiscovery } from "./api";
import type { ArtifactDiscoveryResponse, ArtifactSummary, StageId } from "./types";

export interface ArtifactDiscoveryPickerProps {
  workSlug: string;
  stage: StageId;
  catalogVersion: string;
  artifacts: ArtifactSummary[];
  selectedId: string;
  selectedVersion?: string;
  total: number;
  onSelect: (artifact: ArtifactSummary) => void;
  label: string;
  artifactLabel?: (artifact: ArtifactSummary) => string;
}

const OPTION_SEPARATOR = "\u0000";

function optionKey(artifact: ArtifactSummary): string {
  return `${artifact.id}${OPTION_SEPARATOR}${artifact.version}`;
}

function uniqueArtifacts(values: ArtifactSummary[]): ArtifactSummary[] {
  const seen = new Set<string>();
  const result: ArtifactSummary[] = [];
  for (const artifact of values) {
    const key = optionKey(artifact);
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(artifact);
  }
  return result;
}

function termsFor(value: string): string[] {
  return boundedLocationSearch(value).trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
}

function matchesSearch(artifact: ArtifactSummary, terms: string[]): boolean {
  const haystack = `${artifact.name} ${artifact.path}`.toLocaleLowerCase();
  return terms.every((term) => haystack.includes(term));
}

export function ArtifactDiscoveryPicker({
  workSlug,
  stage,
  catalogVersion,
  artifacts,
  selectedId,
  selectedVersion,
  total,
  onSelect,
  label,
  artifactLabel,
}: ArtifactDiscoveryPickerProps) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [history, setHistory] = useState<number[]>([]);
  const [page, setPage] = useState<ArtifactDiscoveryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const generation = useRef(0);

  const selected = useMemo(() => {
    if (!selectedId) return null;
    return artifacts.find((item) => item.id === selectedId && (selectedVersion === undefined || item.version === selectedVersion)) ?? null;
  }, [artifacts, selectedId, selectedVersion]);
  const initialArtifacts = useMemo(() => uniqueArtifacts([
    ...artifacts.slice(0, 50),
    ...(selected ? [selected] : []),
  ]), [artifacts, selected]);
  const inventoryTotal = Math.max(0, total);
  const requiresDiscovery = inventoryTotal > initialArtifacts.length;
  const normalizedSearch = boundedLocationSearch(search).trim();
  const searchTerms = useMemo(() => termsFor(search), [search]);

  useEffect(() => {
    const currentGeneration = generation.current + 1;
    generation.current = currentGeneration;
    const controller = new AbortController();
    if (!requiresDiscovery) {
      setLoading(false);
      setError(null);
      setPage(null);
      return () => controller.abort();
    }
    setLoading(true);
    setError(null);
    loadArtifactDiscovery(workSlug, stage, {
      offset,
      limit: 50,
      search: normalizedSearch,
      catalogVersion,
    }, artifactRequestOptions(controller.signal)).then((value) => {
      if (generation.current !== currentGeneration) return;
      setPage(value);
      setLoading(false);
    }).catch((caught: unknown) => {
      if (generation.current !== currentGeneration || isRequestAborted(caught)) return;
      setLoading(false);
      setError(caught instanceof Error ? caught.message : "Artifact discovery could not be loaded.");
    });
    return () => controller.abort();
  }, [catalogVersion, normalizedSearch, offset, requiresDiscovery, retry, stage, workSlug]);

  const localMatches = useMemo(() => initialArtifacts.filter((item) => matchesSearch(item, searchTerms)), [initialArtifacts, searchTerms]);
  const pageArtifacts = page?.artifacts ?? (requiresDiscovery ? (normalizedSearch ? [] : initialArtifacts) : localMatches);
  const options = useMemo(() => uniqueArtifacts([
    ...pageArtifacts,
    ...(selected ? [selected] : []),
  ]), [pageArtifacts, selected]);
  const visibleCount = page ? options.length : localMatches.length;
  const matchedCount = page?.matched ?? localMatches.length;
  const previousOffset = history.length ? history[history.length - 1] : null;
  const nextOffset = page?.page.next_offset ?? null;
  const selectedOption = selected ? optionKey(selected) : "";

  const changeSearch = (value: string) => {
    setSearch(value);
    setOffset(0);
    setHistory([]);
    setPage(null);
    setError(null);
  };
  const goNext = () => {
    if (nextOffset === null || loading) return;
    setHistory((value) => [...value, offset]);
    setOffset(nextOffset);
  };
  const goPrevious = () => {
    if (previousOffset === null || loading) return;
    setHistory((value) => value.slice(0, -1));
    setOffset(previousOffset);
  };

  return <div className="source-picker artifact-discovery-picker">
    <label>{label} search<input type="search" aria-label={`${label} search`} value={search} onChange={(event) => changeSearch(event.target.value)} placeholder="Name or path" /></label>
    <label>{label}<select aria-label={label} value={selectedOption} onChange={(event) => {
      const artifact = options.find((item) => optionKey(item) === event.target.value);
      if (artifact) onSelect(artifact);
    }}>
      {!selected && <option value="">Choose a file</option>}
      {options.map((artifact) => <option key={optionKey(artifact)} value={optionKey(artifact)}>{artifactLabel?.(artifact) ?? `${artifact.name} — ${artifact.path}`}</option>)}
    </select></label>
    <small aria-live="polite">{loading ? "Loading files…" : `Showing ${visibleCount.toLocaleString()} of ${inventoryTotal.toLocaleString()} files${matchedCount !== inventoryTotal ? ` (${matchedCount.toLocaleString()} match search)` : ""}.`}</small>
    {error&&<p role="status" className="picker-error">{error} <button type="button" onClick={() => setRetry((value) => value + 1)}>Try again</button></p>}
    {(previousOffset !== null || nextOffset !== null)&&<div className="picker-pagination" aria-label={`${label} pages`}>
      <button type="button" onClick={goPrevious} disabled={previousOffset === null || loading}>Previous</button>
      <span>From file {offset+1}</span>
      <button type="button" onClick={goNext} disabled={nextOffset === null || loading}>Next</button>
    </div>}
  </div>;
}
