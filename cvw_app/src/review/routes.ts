import { governedIdentityText, governedLocationText } from "./api";
import type { ArtifactSummary, CorrespondenceSource, ComparePaneRequest, ImageRequest, ReviewWork, SegmentRange, StageId, StageSummary } from "./types";
type ReviewMode = "read" | "compare";
export type CompareFocus = "left" | "right" | "none";

export interface RouteState {
  slug: string | null;
  mode: ReviewMode;
  agentFocus: boolean;
  stage: StageId;
  artifact: string | null;
  version: string | null;
  location: string | null;
  fromStage: StageId | null;
  fromLocation: string | null;
  left: ComparePaneRequest | null;
  right: ComparePaneRequest | null;
  linked: boolean;
  correspondence: string | null;
  range: SegmentRange | null;
  leftRange: SegmentRange | null;
  rightRange: SegmentRange | null;
  leftImage: ImageRequest | null;
  rightImage: ImageRequest | null;
  routeError: string | null;
}

function emptyRoute(): RouteState {
  return {slug:null,mode:"read",agentFocus:false,stage:"source",artifact:null,version:null,location:null,fromStage:null,fromLocation:null,left:null,right:null,linked:false,correspondence:null,range:null,leftRange:null,rightRange:null,leftImage:null,rightImage:null,routeError:null};
}

export function sameRoute(left: RouteState, right: RouteState): boolean {
  // Presentation-only focus changes reuse the exact loaded response and renderer DOM.
  return left.slug === right.slug && left.mode === right.mode && left.stage === right.stage
    && left.artifact === right.artifact && left.version === right.version && left.location === right.location
    && left.fromStage === right.fromStage && left.fromLocation === right.fromLocation
    && JSON.stringify(left.left) === JSON.stringify(right.left) && JSON.stringify(left.right) === JSON.stringify(right.right)
    && left.linked === right.linked && left.correspondence === right.correspondence
    && JSON.stringify(left.range) === JSON.stringify(right.range) && JSON.stringify(left.leftRange) === JSON.stringify(right.leftRange)
    && JSON.stringify(left.rightRange) === JSON.stringify(right.rightRange) && JSON.stringify(left.leftImage) === JSON.stringify(right.leftImage)
    && JSON.stringify(left.rightImage) === JSON.stringify(right.rightImage) && left.routeError === right.routeError;
}

function governedValue(params: URLSearchParams, name: string, maximum: 16 | 256 | 512, identity = false): string {
  const values = params.getAll(name);
  if (values.length !== 1) throw new Error(`${name} must appear exactly once.`);
  if (identity) return governedIdentityText(values[0], name);
  if (maximum === 512) return governedLocationText(values[0], name);
  const value = values[0];
  if (!value.trim() || Array.from(value).length > maximum) throw new Error(`${name} must be nonempty Unicode scalar text within its bound.`);
  return value;
}

function governedStage(value: string, name: string): StageId {
  if (value !== "source" && value !== "tei") throw new Error(`${name} is unknown.`);
  return value;
}

function governedPane(params: URLSearchParams, side: "left" | "right"): ComparePaneRequest {
  const prefix = side === "left" ? "left" : "right";
  return {
    stage: governedStage(governedValue(params, `${prefix}Stage`, 16), `${prefix}Stage`),
    artifact_id: governedValue(params, `${prefix}Artifact`, 256, true),
    artifact_version: governedValue(params, `${prefix}Version`, 256, true),
    location: governedValue(params, `${prefix}Location`, 512),
  };
}

function governedRange(params: URLSearchParams, prefix = ""): SegmentRange | null {
  const startName = prefix ? `${prefix}SegmentStart` : "segmentStart";
  const limitName = prefix ? `${prefix}SegmentLimit` : "segmentLimit";
  const starts = params.getAll(startName);
  const limits = params.getAll(limitName);
  if (!starts.length && !limits.length) return null;
  if (starts.length !== 1 || limits.length !== 1 || !/^\d+$/.test(starts[0]) || !/^\d+$/.test(limits[0])) {
    throw new Error(`${startName} and ${limitName} must appear once together as integers.`);
  }
  const start = Number(starts[0]);
  const limit = Number(limits[0]);
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(limit) || limit < 1) throw new Error("Segment range is outside its integer bound.");
  return {start, limit};
}

function governedImage(params: URLSearchParams, side: "left" | "right"): ImageRequest | null {
  const variants=params.getAll(`${side}Image`), regions=params.getAll(`${side}Region`), digests=params.getAll(`${side}ImageSha256`);
  if(regions.length || digests.length) {
    if(variants.length || regions.length!==1 || digests.length!==1 || !/^[a-f0-9]{64}$/.test(digests[0])
      || !/^(?:0|[1-9][0-9]{0,4}),(?:0|[1-9][0-9]{0,4}),[1-9][0-9]{0,4},[1-9][0-9]{0,4}$/.test(regions[0])) {
      throw new Error(`${side}Region and ${side}ImageSha256 must appear once together as an exact pixel tuple and lowercase SHA-256, without ${side}Image.`);
    }
    return {variant:"region",region:regions[0],source_sha256:digests[0]};
  }
  if(!variants.length)return null;
  if(variants.length!==1 || (variants[0]!=="preview" && variants[0]!=="original"))throw new Error(`${side}Image must be preview or original.`);
  return {variant:variants[0]};
}

export function routeState(): RouteState {
  const match = window.location.pathname.match(/^\/review\/works\/([^/]+)$/);
  const base = emptyRoute();
  const params = new URLSearchParams(window.location.search);
  if (!match) return params.has("focus")?{...base,routeError:"Invalid review route: focus is valid only in Compare mode."}:base;
  let slug: string | null = null;
  try {
    decodeURIComponent(window.location.search);
    slug = governedIdentityText(decodeURIComponent(match[1]), "work slug");
    if (params.getAll("mode").length > 1) throw new Error("mode may appear at most once.");
    if (params.get("mode") === "compare") {
      const allowed = new Set(["mode","focus","leftStage","leftArtifact","leftVersion","leftLocation","rightStage","rightArtifact","rightVersion","rightLocation","linked","correspondence","leftSegmentStart","leftSegmentLimit","rightSegmentStart","rightSegmentLimit","leftImage","leftRegion","leftImageSha256","rightImage","rightRegion","rightImageSha256"]);
      for (const name of params.keys()) if (!allowed.has(name)) throw new Error(`${name} is not valid in Compare mode.`);
      const focus = params.getAll("focus");
      if (focus.length > 1 || (focus.length === 1 && focus[0] !== "agent")) throw new Error("focus must appear at most once with the value agent.");
      const linked = governedValue(params, "linked", 16);
      if (linked !== "true" && linked !== "false") throw new Error("linked must be true or false.");
      const correspondence = governedValue(params, "correspondence", 256, true);
      return {...base,slug,mode:"compare",agentFocus:focus.length === 1,left:governedPane(params,"left"),right:governedPane(params,"right"),linked:linked === "true",correspondence:correspondence === "absent" ? null : correspondence,leftRange:governedRange(params,"left"),rightRange:governedRange(params,"right"),leftImage:governedImage(params,"left"),rightImage:governedImage(params,"right")};
    }
    if (params.has("mode")) throw new Error("mode is unknown. This viewer supports only Read and Compare.");
    const allowed = new Set(["stage","artifact","version","location","fromStage","fromLocation","segmentStart","segmentLimit","rightStage","rightArtifact","rightVersion","rightLocation"]);
    for (const name of params.keys()) if (!allowed.has(name)) throw new Error(`${name} is not valid in Read mode.`);
    const stage = governedStage(governedValue(params,"stage",16), "stage");
    const artifact = governedValue(params,"artifact",256,true);
    const version = governedValue(params,"version",256,true);
    const location = governedValue(params,"location",512);
    const fromStages = params.getAll("fromStage");
    const fromLocations = params.getAll("fromLocation");
    let fromStage: StageId | null = null;
    let fromLocation: string | null = null;
    if (fromStages.length || fromLocations.length) {
      if (fromStages.length !== 1 || fromLocations.length !== 1) throw new Error("fromStage and fromLocation must appear once together.");
      fromStage = governedStage(fromStages[0], "fromStage");
      fromLocation = governedLocationText(fromLocations[0], "fromLocation");
    }
    const right=["rightStage","rightArtifact","rightVersion","rightLocation"].some((name)=>params.has(name))?governedPane(params,"right"):null;
    if(right?.stage===stage)throw new Error("The remembered reading version must be the other stage.");
    return {...base,slug,stage,artifact,version,location,fromStage,fromLocation,right,range:governedRange(params)};
  } catch (caught) {
    return {...base,slug,routeError:`Invalid review route: ${(caught as Error).message}`};
  }
}

function rememberOther(params:URLSearchParams, other?:ComparePaneRequest|null) {
  if(other)for(const [name,value] of Object.entries({rightStage:other.stage,rightArtifact:other.artifact_id,rightVersion:other.artifact_version,rightLocation:other.location}))params.set(name,value);
}

export function stageRoute(slug: string, stage: StageSummary, from?: CorrespondenceSource, other?:ComparePaneRequest|null): string {
  if (!stage.selected_artifact) throw new Error("Read requires an upstream-selected artifact.");
  const params = new URLSearchParams({stage:stage.id,artifact:stage.selected_artifact.id,version:stage.selected_artifact.version,location:"start"});
  if (from) { params.set("fromStage",from.stage); params.set("fromLocation",from.location); }
  rememberOther(params,other);
  return `/review/works/${encodeURIComponent(slug)}?${params}`;
}

export function artifactRoute(slug: string, stage: StageId, artifact: ArtifactSummary, other?:ComparePaneRequest|null): string {
  const params = new URLSearchParams({stage,artifact:artifact.id,version:artifact.version,location:"start"});
  rememberOther(params,other);
  return `/review/works/${encodeURIComponent(slug)}?${params}`;
}

export function recordedStageRoute(slug: string, pane: ComparePaneRequest, other?:ComparePaneRequest|null): string {
  const params = new URLSearchParams({stage:pane.stage,artifact:pane.artifact_id,version:pane.artifact_version,location:pane.location});
  rememberOther(params,other);
  return `/review/works/${encodeURIComponent(slug)}?${params}`;
}

export function compareRoute(slug: string, left: ComparePaneRequest, right: ComparePaneRequest, linked: boolean, correspondence: string | null, leftRange?: SegmentRange | null, rightRange?: SegmentRange | null, agentFocus = false, leftImage?: ImageRequest | null, rightImage?: ImageRequest | null): string {
  const params = new URLSearchParams({
    mode:"compare",leftStage:left.stage,leftArtifact:left.artifact_id,leftVersion:left.artifact_version,leftLocation:left.location,
    rightStage:right.stage,rightArtifact:right.artifact_id,rightVersion:right.artifact_version,rightLocation:right.location,
    linked:String(linked),correspondence:correspondence ?? "absent",
  });
  if (leftRange) { params.set("leftSegmentStart", String(leftRange.start)); params.set("leftSegmentLimit", String(leftRange.limit)); }
  if (rightRange) { params.set("rightSegmentStart", String(rightRange.start)); params.set("rightSegmentLimit", String(rightRange.limit)); }
  for(const [side,selection] of [["left",leftImage],["right",rightImage]] as const) {
    if(!selection)continue;
    if(selection.variant==="region") { params.set(`${side}Region`,selection.region);params.set(`${side}ImageSha256`,selection.source_sha256); }
    else params.set(`${side}Image`,selection.variant);
  }
  if (agentFocus) params.set("focus", "agent");
  return `/review/works/${encodeURIComponent(slug)}?${params}`;
}

export function rangedStageRoute(route: RouteState, range: SegmentRange): string {
  if (!route.slug || !route.artifact || !route.version || !route.location) throw new Error("Read paging requires an exact recorded route.");
  const params = new URLSearchParams({stage:route.stage,artifact:route.artifact,version:route.version,location:route.location,segmentStart:String(range.start),segmentLimit:String(range.limit)});
  if (route.fromStage && route.fromLocation) { params.set("fromStage", route.fromStage); params.set("fromLocation", route.fromLocation); }
  rememberOther(params,route.right);
  return `/review/works/${encodeURIComponent(route.slug)}?${params}`;
}

export function selectedPane(stage: StageSummary, location = "start"): ComparePaneRequest {
  if (!stage.selected_artifact) throw new Error("Compare requires an upstream-selected artifact.");
  return {stage:stage.id,artifact_id:stage.selected_artifact.id,artifact_version:stage.selected_artifact.version,location};
}

export function correspondenceFor(work: ReviewWork, left: ComparePaneRequest, right: ComparePaneRequest) {
  return work.correspondence_sources.find((item) => item.left_stage === left.stage && item.right_stage === right.stage
    && item.left_artifact_id === left.artifact_id && item.left_artifact_version === left.artifact_version
    && item.right_artifact_id === right.artifact_id && item.right_artifact_version === right.artifact_version) ?? null;
}

export function mappedTarget(work: ReviewWork, left: ComparePaneRequest, right: ComparePaneRequest): { source: string; location: string } | null {
  const source = correspondenceFor(work,left,right);
  if (source?.state !== "known") return null;
  const location = source.mappings.find((item) => item.left_location === left.location)?.right_location;
  return location ? {source:source.id,location} : null;
}

export function navigateRoute(path: string, compareFocus?: CompareFocus) {
  window.history.pushState(compareFocus ? {compareFocus} : {}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function navigateLibrary() { navigateRoute("/review"); }
