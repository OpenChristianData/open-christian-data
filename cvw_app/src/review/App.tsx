import { sameRoute, routeState, stageRoute, artifactRoute, recordedStageRoute, compareRoute, rangedStageRoute, selectedPane, correspondenceFor, mappedTarget, navigateRoute, navigateLibrary, type RouteState, type CompareFocus } from "./routes";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { artifactRequestOptions, boundedLocationSearch, isRequestAborted, loadCompareViewAutoPaged, loadLocations, loadReviewCatalogPage, loadReviewSession, loadReviewWork, loadStageViewAutoPaged, ReviewRequestError, type WorkSelection } from "./api";
import { renderPresentation, type BytesIdentity } from "./renderers";
import { ArtifactDiscoveryPicker } from "./ArtifactDiscoveryPicker";
import type { ArtifactSummary, CandidateValidationMember, CandidateValidationSummary, ComparePaneRequest, CompareView, ImageRequest, CorrespondenceSource, DocumentNode, LocationDiscovery, ReviewCatalog, ReviewWork, SegmentRange, SessionDescriptor, StageId, StageSummary, StageView } from "./types";

type CandidateSessionState = "all" | "no-candidate" | "choose-source" | "available" | "unsupported" | "invalid";

function stageName(stage: StageId): string {
  return stage === "source" ? "Source" : "Reconstructed text";
}

interface LoadedStage { route: RouteState; view: StageView }
interface LoadedCompare { route: RouteState; view: CompareView; generation: number }
interface LoadedWork { key: string; work: ReviewWork; catalogVersion: string }

interface AppError {
  message: string;
  code: string | null;
  requestId: string | null;
  status: number | null;
  path: string | null;
  retryable: boolean;
}

function appError(caught: unknown): AppError {
  if (caught instanceof ReviewRequestError) {
    return {message:caught.message,code:caught.code,requestId:caught.requestId,status:caught.status,path:caught.path,retryable:caught.retryable};
  }
  return {message:caught instanceof Error?caught.message:"The review request failed.",code:null,requestId:null,status:null,path:null,retryable:false};
}

function copyableJson(value: unknown): Promise<void> {
  if (!navigator.clipboard?.writeText) return Promise.reject(new Error("Clipboard access is unavailable."));
  return navigator.clipboard.writeText(JSON.stringify(value,null,2));
}

function SessionBanner({ session, loading, error, onRefresh }: { session: SessionDescriptor | null; loading: boolean; error: AppError | null; onRefresh: () => void }) {
  const [copyStatus,setCopyStatus]=useState<string|null>(null);
  const copy=async()=>{
    if(!session)return;
    try{await copyableJson({contract:"ocd-cvw-session-diagnostics-v1",session:session.session});setCopyStatus("Session details copied.");}
    catch{setCopyStatus("Could not copy session details. Try again.");}
  };
  const state=session?.session.state??(loading?"loading":"unavailable");
  return <section className="session-banner" aria-label="CVW session diagnostics">
    <details className="session-identity"><summary>Session details</summary>
      <p>This app is read-only. It does not edit, approve, or publish books.</p>
      <div className="session-summary"><span className={`session-pill session-${state}`}>{session?`${state} · ${abbreviatedDigest(session.session.session_id)}`:state}</span></div>
      <div className="session-actions"><button type="button" onClick={onRefresh} disabled={loading}>{loading?"Refreshing session…":"Refresh session"}</button>{session&&<button type="button" onClick={copy}>Copy session details</button>}</div>
      {session&&<dl><div><dt>Session ID</dt><dd><code title={session.session.session_id}>{session.session.session_id}</code></dd></div><div><dt>Bound origin</dt><dd>{session.session.origin??"Pending"}</dd></div><div><dt>Catalog SHA-256</dt><dd><code title={session.session.catalog_sha256??""}>{session.session.catalog_sha256?abbreviatedDigest(session.session.catalog_sha256):"Pending"}</code></dd></div><div><dt>Implementation SHA-256</dt><dd><code title={session.session.implementation_sha256??""}>{session.session.implementation_sha256?abbreviatedDigest(session.session.implementation_sha256):"Pending"}</code></dd></div>{session.session.preflight_elapsed_ms!==undefined&&<div><dt>Preflight</dt><dd>{session.session.preflight_elapsed_ms.toLocaleString()} ms</dd></div>}</dl>}
    </details>
    {error&&<p role="status" className="session-error">{session?`Could not refresh session details: ${error.message}`:error.message}</p>}
    {copyStatus&&<p role="status" className="session-copy-status">{copyStatus}</p>}
  </section>;
}

function ErrorView({ error, session, onRetry, onReturn, catalogFailure, reviewRoute }: { error: AppError; session: SessionDescriptor | null; onRetry: () => void; onReturn: () => void; catalogFailure: boolean; reviewRoute?: string }) {
  const [copyStatus,setCopyStatus]=useState<string|null>(null);
  const copy=async()=>{
    const diagnostics={
      contract:"ocd-cvw-diagnostics-v1",
      route:window.location.href,
      error:{message:error.message,code:error.code,request_id:error.requestId,status:error.status,path:error.path,retryable:error.retryable},
      session:session?.session??null,
    };
    try{await copyableJson(diagnostics);setCopyStatus("Error details copied.");}
    catch{setCopyStatus("Could not copy error details. Try again.");}
  };
  return <main id="main-content" className="main" data-review-state="error" data-review-route={reviewRoute}><div role="alert" className="error"><h1>{catalogFailure?"Review unavailable":"Artifact unavailable"}</h1><p>{error.message}</p><dl className="error-details">{error.code&&<div><dt>Error code</dt><dd><code>{error.code}</code></dd></div>}{error.status!==null&&<div><dt>HTTP status</dt><dd>{error.status}</dd></div>}{error.requestId&&<div><dt>Request ID</dt><dd><code>{error.requestId}</code></dd></div>}{error.path&&<div><dt>Request</dt><dd><code>{error.path}</code></dd></div>}</dl><div className="error-actions"><button type="button" onClick={onRetry}>{error.retryable?"Retry request":"Try again"}</button><button type="button" onClick={copy}>Copy error details</button><button type="button" onClick={onReturn}>Return to library</button></div><span role="status" aria-live="polite">{copyStatus??null}</span></div></main>;
}

function Status({ value }: { value: StageView["availability"] }) {
  const label = value === "available" ? "Available" : value === "unavailable" ? "Unavailable" : value === "selection-required" ? "Choose source" : "Unsupported";
  return <span className={`status status-${value}`}><span aria-hidden="true" className="status-dot" />{label}</span>;
}

function ExactFallbackLink({ fallback }: { fallback: NonNullable<StageView["exact_fallback"]> }) {
  return fallback.kind === "exact-bytes"
    ? <a href={fallback.target} download target="_blank" rel="noreferrer">Download original file</a>
    : <a href={fallback.target} target="_blank" rel="noreferrer">Open original text</a>;
}

function NativeOpenControl({ view }: { view: StageView }) {
  if (view.exact_fallback?.kind === "exact-bytes") return null;
  if (!(view.native_open.allowed && view.native_open.target && view.capabilities?.read.available)) return null;
  return <a href={view.native_open.target} download target="_blank" rel="noreferrer">Download file</a>;
}

function SegmentControls({ label, view, range, onRange, windowSize }: { label: string; view: StageView; range: SegmentRange | null; onRange: (range: SegmentRange) => void; windowSize?: number }) {
  if (!view.paging || view.paging.mode !== "segments" || view.paging.segment_count < 2) return null;
  const count = view.paging.segment_count;
  const maximum = Math.min(windowSize ?? view.paging.max_segments_per_request, view.paging.max_segments_per_request);
  const start = range?.start ?? view.paging.segments[0]?.index ?? 0;
  const limit = range?.limit ?? Math.min(view.paging.segments.length || maximum, maximum, count - start);
  const end = Math.min(start + limit, count);
  const previousStart = Math.max(0, start - maximum);
  const nextStart = end;
  return <nav className="segment-controls" aria-label={`${label} segment navigation`}>
    <button type="button" disabled={start === 0} onClick={()=>onRange({start:previousStart,limit:Math.min(maximum,count-previousStart)})}>Previous section</button>
    <span aria-live="polite">Sections {start + 1}–{end} of {count}</span>
    <button type="button" disabled={end >= count} onClick={()=>onRange({start:nextStart,limit:Math.min(maximum,count-nextStart)})}>Next section</button>
  </nav>;
}

function LocationRangeWarning({ label, view }: { label: string; view: StageView }) {
  if(view.location_state!=="location-outside-range"||!view.location_message)return null;
  return <div className="notice" role="status" aria-label={`${label} recorded location warning`}>
    <strong>This passage is outside the sections currently loaded.</strong>
    <span>{view.location_message}</span>
  </div>;
}

function abbreviatedDigest(value: string): string {
  return `${value.slice(0, 12)}…`;
}

function ValidationIdentity({ validation, validations }: { validation: CandidateValidationSummary | null; validations?: CandidateValidationMember[] }) {
  const members=validations?.length?validations:validation?[validation]:[];
  if(!members.length)return null;
  return <aside className="validation-identity" role="status" aria-label="Candidate validation identity"><details className="validation-details"><summary>Validation details</summary>
    <p>Automated checks passed for this review copy.</p><p>This viewer does not record approval or publication decisions.</p>
    <div className="validation-hashes">{members.map((member,index)=><div key={index} className="validation-member">
      {validations?.[index]&&<strong>Part {index+1} · {validations[index].source_id}</strong>}
      <span>Validation report <code title={member.report_sha256}>{abbreviatedDigest(member.report_sha256)}</code></span>
      <span>Text package <code title={member.candidate_sha256}>{abbreviatedDigest(member.candidate_sha256)}</code></span>
      <span>Source manifest <code title={member.source_manifest_sha256}>{abbreviatedDigest(member.source_manifest_sha256)}</code></span>
    </div>)}</div>
  </details></aside>;
}

function SourceAuthoritySelect({ work, selectedId, onSelect }: { work: ReviewWork; selectedId: string | null; onSelect: (artifact: ArtifactSummary) => void }) {
  const source=work.stages.find((stage)=>stage.id==="source");
  if(!source||(source.artifact_discovery?.total??source.artifacts.length)<2)return null;
  const selected=source.artifacts.find((artifact)=>artifact.id===selectedId)??null;
  return <section className="source-authority-select" aria-label="Retained source selection">
    {!selected&&<p>Choose one of the {(source.artifact_discovery?.total??source.artifacts.length).toLocaleString()} source files to read.</p>}
    <SourceArtifactPicker work={work} stage="source" artifacts={source.artifacts} selectedId={selectedId} onSelect={onSelect} filterLabel="Find a source" selectLabel="Source file" allowEmpty/>
    <details><summary>File details</summary><p>{selected?<>Selected <strong>{selected.name}</strong> · <code>{selected.path}</code> · {selected.bytes.toLocaleString()} bytes · SHA-256 <code title={selected.sha256}>{abbreviatedDigest(selected.sha256)}</code></>:null}</p></details>
  </section>;
}

function candidateArtifactLabel(work: ReviewWork, artifact: ArtifactSummary): string {
  const member = work.candidate_validations?.find((item) => item.tei_artifact_id === artifact.id);
  return `${member?.source_id ?? "Candidate member"} — ${artifact.name} — ${artifact.path}`;
}

function CandidateMemberSelect({ work, selectedId, onSelect }: { work: ReviewWork; selectedId: string | null; onSelect: (artifact: ArtifactSummary) => void }) {
  const tei = work.stages.find((stage) => stage.id === "tei");
  if (!tei || (tei.artifact_discovery?.total ?? tei.artifacts.length) < 2 || (work.candidate_validations?.length ?? 0) < 2) return null;
  const selected = tei.artifacts.find((artifact) => artifact.id === selectedId) ?? null;
  return <section className="source-authority-select candidate-member-select" aria-label="Text part selection">
    {!selected&&<p>Choose one of the {(tei.artifact_discovery?.total??tei.artifacts.length).toLocaleString()} text parts to read.</p>}
    <SourceArtifactPicker work={work} stage="tei" artifacts={tei.artifacts} selectedId={selectedId} onSelect={onSelect} filterLabel="Find a text part" selectLabel="Text part" allowEmpty emptyLabel="Choose a text part" artifactLabel={(artifact) => candidateArtifactLabel(work, artifact)} />
    <details><summary>File details</summary><p>{selected ? <>Selected <strong>{candidateArtifactLabel(work, selected)}</strong> · SHA-256 <code title={selected.sha256}>{abbreviatedDigest(selected.sha256)}</code></> : null}</p></details>
  </section>;
}

function documentContainsLocation(nodes: DocumentNode[], location: string): boolean {
  return nodes.some((node) => node.location === location || documentContainsLocation(node.children ?? [], location));
}

interface SourcePickerProps { artifacts: ArtifactSummary[]; selectedId: string | null; onSelect: (artifact: ArtifactSummary) => void; filterLabel: string; selectLabel: string; allowEmpty?: boolean; emptyLabel?: string; artifactLabel?: (artifact: ArtifactSummary) => string; work?: ReviewWork; stage?: StageId }

function SourceArtifactPicker(props: SourcePickerProps) {
  const stage=props.work?.stages.find((item)=>item.id===props.stage);
  const version=props.work?.approved_roots_discovery?.catalog_version;
  if(props.work&&props.stage&&version&&stage?.artifact_discovery&&!stage.artifact_discovery.complete){
    return <ArtifactDiscoveryPicker key={`${props.work.slug}:${props.stage}:${version}`} workSlug={props.work.slug} stage={props.stage} catalogVersion={version} artifacts={props.artifacts} selectedId={props.selectedId??""} selectedVersion={props.artifacts.find((item)=>item.id===props.selectedId)?.version} total={stage.artifact_discovery.total} onSelect={props.onSelect} label={props.selectLabel} artifactLabel={props.artifactLabel}/>;
  }
  return <LocalSourceArtifactPicker {...props}/>;
}

function LocalSourceArtifactPicker({ artifacts, selectedId, onSelect, filterLabel, selectLabel, allowEmpty=false, emptyLabel="Choose a source", artifactLabel }: SourcePickerProps) {
  const [filter,setFilter]=useState("");
  const terms=useMemo(()=>filter.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean),[filter]);
  const visible=useMemo(()=>artifacts.filter((artifact)=>artifact.id===selectedId||terms.every((term)=>`${artifact.name} ${artifact.path}`.toLocaleLowerCase().includes(term))),[artifacts,selectedId,terms]);
  return <div className="source-picker">
    <label>{filterLabel}<input type="search" value={filter} onChange={(event)=>setFilter(event.target.value)} placeholder="Name or path" /></label>
    <label>{selectLabel}<select aria-label={selectLabel} value={selectedId??""} onChange={(event)=>{const artifact=artifacts.find((item)=>item.id===event.target.value);if(artifact)onSelect(artifact);}}>{allowEmpty&&<option value="">{emptyLabel}</option>}{visible.map((artifact)=><option key={artifact.id} value={artifact.id}>{artifactLabel?.(artifact) ?? `${artifact.name} — ${artifact.path}`}</option>)}</select></label>
    <small aria-live="polite">{visible.length} of {artifacts.length} files</small>
  </div>;
}

function Shell({ children, libraryActive, session, sessionLoading, sessionError, onRefreshSession, onNavigateLibrary, agentFocus = false }: { children: ReactNode; libraryActive: boolean; session: SessionDescriptor | null; sessionLoading: boolean; sessionError: AppError | null; onRefreshSession: () => void; onNavigateLibrary: () => void; agentFocus?: boolean }) {
  const sessionWarning=sessionLoading?"Refreshing session diagnostics…":sessionError?.message??(!session?"Session identity is unavailable.":session.session.state!=="ready"?`Session ${session.session.state}. ${session.session.error_message??""}`:null);
  return <div className={`review-shell${agentFocus?" agent-focus-shell":""}`}>
    <a className="skip-link" href="#main-content">Skip to review content</a>
    <header className="topbar"><a className="brand" href="/review" onClick={(event)=>{event.preventDefault();onNavigateLibrary();}}><span aria-hidden="true" className="book-mark">▤</span><span><strong>CVW</strong><small>Open Christian Data</small></span></a><p>Read and compare texts</p></header>
    {sessionWarning&&<div className="notice" role="status" aria-label="Session warning">{sessionWarning}</div>}
    <div className="shell-body"><aside className="rail" aria-label="Review navigation"><span className="rail-label">REVIEW</span><a aria-current={libraryActive?"page":undefined} href="/review" onClick={(event)=>{event.preventDefault();onNavigateLibrary();}}>Library</a></aside>{children}</div>
    {!agentFocus&&<SessionBanner session={session} loading={sessionLoading} error={sessionError} onRefresh={onRefreshSession}/>}
  </div>;
}

function WorkList({ catalog, onMore, loadingMore, pageError, query, stateFilter, onSearch }: { catalog: ReviewCatalog; onMore: () => void; loadingMore: boolean; pageError: AppError | null; query: string; stateFilter: CandidateSessionState; onSearch: (query:string,state:CandidateSessionState)=>void }) {
  const works=catalog.works;
  return <main id="main-content" className="main library" tabIndex={-1}>
    <section className="page-title"><h1>Library</h1><p>Read a source document or compare it with the reconstructed text.</p></section>
    <section className="work-panel" aria-label="Books">
      <div className="panel-tools"><div><p aria-live="polite">{catalog.page.total.toLocaleString()} {catalog.page.total===1?"book":"books"}{query?" found":""}</p></div><div className="library-filters"><label>Search books<input type="search" value={query} onChange={(event)=>onSearch(event.target.value,stateFilter)} placeholder="Title or author" /></label><label>Show<select value={stateFilter} onChange={(event)=>onSearch(query,event.target.value as CandidateSessionState)}><option value="all">All books</option><option value="available">Ready to compare</option><option value="choose-source">Choose a source</option><option value="no-candidate">Not loaded</option><option value="unsupported">Cannot display</option><option value="invalid">Needs attention</option></select></label>{(query||stateFilter!=="all")&&<button type="button" className="clear-filters" onClick={()=>onSearch("","all")}>Clear filters</button>}</div></div>
      <div className="table-scroll"><table role="table" aria-label="Books"><thead><tr><th scope="col">Book</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Open</span></th></tr></thead><tbody>{works.map((work)=>{
        const first=work.stages.find((stage)=>stage.availability==="available"&&stage.selected_artifact);
        const state=candidateSessionState(work);
        return <tr role="row" key={work.slug}><td role="cell"><strong>{work.title}</strong><span>{work.creator==="Creator not recorded"?"":work.creator}</span></td><td role="cell" data-label="Status"><span className={`session-state session-${state.value}`}>{state.label}</span>{state.value!=="available"&&state.value!=="no-candidate"&&<small>{state.detail}</small>}</td><td role="cell">{first?<button className="open-work" onClick={()=>navigateRoute(stageRoute(work.slug,first))} aria-label={`Open ${work.title}`}>Open <span aria-hidden="true">→</span></button>:<span className="not-loaded">—<span className="sr-only">Not available to open</span></span>}</td></tr>;
      })}</tbody></table></div>
      {works.length===0&&<p className="empty">No books match these filters. Try another search or clear the filters.</p>}
      <div className="library-footer"><p className="library-page-summary">Showing {works.length.toLocaleString()} of {catalog.page.total.toLocaleString()}</p>{catalog.page.next_offset!==null&&<button type="button" onClick={onMore} disabled={loadingMore}>{loadingMore?"Loading…":"Load more books"}</button>}</div>
      {works.some((work)=>candidateSessionState(work).value==="no-candidate")&&<details className="library-help"><summary>Why are some books not loaded?</summary><p>The catalog includes books that were not opened with this session. To view one, restart CVW with its candidate folder.</p></details>}
      {pageError&&<p role="alert">{pageError.message} Select Load more books to try again.</p>}
    </section>
  </main>;
}

function ReviewedIdentityControl({ work, source, tei, exact, imageScope }: { work: ReviewWork; source: ArtifactSummary | null; tei: ArtifactSummary | null; exact: boolean; imageScope?: unknown }) {
  const [copyStatus,setCopyStatus]=useState<string|null>(null);
  const [fallbackPayload,setFallbackPayload]=useState<string|null>(null);
  const selectedMemberValidation=tei&&work.candidate_validations?.find((item)=>item.tei_artifact_id===tei.id);
  const validation=selectedMemberValidation??work.candidate_validation;
  const sourceMatchesValidation=!selectedMemberValidation||Boolean(source&&(selectedMemberValidation.source_artifact_ids.includes(source.id)||source.candidate_validation_tei_artifact_id===selectedMemberValidation.tei_artifact_id));
  const canCopy=Boolean(validation&&source&&tei&&exact&&sourceMatchesValidation);
  const copy=async()=>{
    if(!validation||!source||!tei||!exact||!sourceMatchesValidation)return;
    const payload={
      contract:"ocd-cvw-reviewed-identity-v1",
      work_id:work.slug,
      ...(imageScope ? {image_view_scope:imageScope} : {}),
      source:{artifact_id:source.id,version:source.version,sha256:source.sha256,path:source.path},
      candidate:{artifact_id:tei.id,version:tei.version,artifact_sha256:tei.sha256,path:tei.path,package_sha256:validation.candidate_sha256},
      validation:{status:validation.status,report_sha256:validation.report_sha256,source_manifest_sha256:validation.source_manifest_sha256},
    };
    const serialized=JSON.stringify(payload,null,2);
    try{
      await navigator.clipboard.writeText(serialized);
      setFallbackPayload(null);
      setCopyStatus("Comparison details copied.");
    }catch{
      setFallbackPayload(serialized);
      setCopyStatus("Could not use the clipboard. Select and copy the details below.");
    }
  };
  return <section className="reviewed-identity" aria-label="External decision handoff">
    <button type="button" disabled={!canCopy} onClick={copy}>Copy comparison details</button>
    <span aria-live="polite">{copyStatus??(validation&&source&&tei&&!sourceMatchesValidation?"This source does not belong to the selected text. Choose a matching pair.":"Includes file versions and validation report IDs.")}</span>
    {fallbackPayload&&<label className="reviewed-identity-fallback">Comparison details<textarea readOnly value={fallbackPayload} onFocus={(event)=>event.currentTarget.select()} /></label>}
  </section>;
}

function candidateSessionState(work: ReviewWork): { value: Exclude<CandidateSessionState,"all">; label: string; detail: string } {
  const source=work.stages.find((stage)=>stage.id==="source");
  const tei=work.stages.find((stage)=>stage.id==="tei");
  if(!work.candidate_validation&&!work.candidate_validations?.length)return {value:"no-candidate",label:"Not loaded",detail:"No candidate folder was supplied for this book."};
  if(source?.availability==="unsupported"&&tei?.availability==="available")return {value:"unsupported",label:"Source needs download",detail:"Read the reconstructed text here or download the original source."};
  if(source?.availability==="unsupported"||tei?.availability==="unsupported")return {value:"unsupported",label:"Cannot display",detail:"This file format cannot be displayed here."};
  if(source?.availability==="selection-required")return {value:"choose-source",label:"Choose a source",detail:"More than one source is available."};
  if(source?.availability==="available"&&tei?.availability==="available")return {value:"available",label:"Ready to compare",detail:"Source and reconstructed text are loaded."};
  return {value:"invalid",label:"Needs attention",detail:"The source or reconstructed text could not be loaded."};
}

function StageRail({ work, selected, location, route }: { work: ReviewWork; selected: StageId; location: string; route:RouteState }) {
  const current:ComparePaneRequest={stage:selected,artifact_id:route.artifact!,artifact_version:route.version!,location};
  return <nav className="stage-rail" aria-label="Artifact stages"><p>Read</p>{work.stages.map((stage)=>stage.id===selected
    ? <div key={stage.id} className="stage-row selected current-stage" aria-current="page"><span>{stageName(stage.id)}</span></div>
    : <button key={stage.id} type="button" className="stage-row" disabled={!["available","unsupported"].includes(stage.availability)||!stage.selected_artifact} onClick={()=>navigateRoute(route.right?.stage===stage.id?recordedStageRoute(work.slug,route.right,current):stageRoute(work.slug,stage,{stage:selected,location},current))}><span>{stageName(stage.id)}</span></button>)}</nav>;
}

function PresentationDetails({view}:{view:StageView}) {
  return view.presentation&&<details className="presentation-details"><summary>About this view{view.presentation.limitations?.length ? ` (${view.presentation.limitations.length} limitations)` : ""}</summary><p>{view.presentation.freshness==="admitted-snapshot"?"This view was loaded when the session started. Restart CVW after changing the files.":"The displayed file matches the selected version."}{view.presentation.text_encoding ? ` Text decoded as ${view.presentation.text_encoding}.` : ""}</p>{view.presentation.limitations?.length ? <ul>{view.presentation.limitations.map((limit,index)=><li key={index}>{limit}</li>)}</ul>:null}</details>;
}

function Reader({ work, view, route }: { work: ReviewWork; view: StageView; route: RouteState }) {
  const contextLost=view.recorded_context.state!=="exact";
  const recordedPane:ComparePaneRequest|null=route.artifact&&route.version&&route.location?{stage:view.stage.id,artifact_id:route.artifact,artifact_version:route.version,location:route.location}:null;
  const otherStage=work.stages.find((stage)=>stage.id!==view.stage.id&&stage.availability==="available"&&stage.selected_artifact);
  const openCompare=()=>{
    if(!recordedPane||!otherStage)return;
    const right=route.right??selectedPane(otherStage);
    const source=correspondenceFor(work,recordedPane,right);
    navigateRoute(compareRoute(work.slug,recordedPane,right,false,source?.id??null),"left");
  };
  useEffect(()=>{
    if(contextLost||!view.location)return;
    if(view.location.value==="start"){window.scrollTo(0,0);return;}
    const target=document.getElementById(view.location.value);
    if(target){for(let parent=target.parentElement;parent;parent=parent.parentElement){if(parent instanceof HTMLDetailsElement&&parent.classList.contains("book-details"))parent.open=true;}}
    target?.focus({preventScroll:true}); target?.scrollIntoView?.({block:"center"});
  },[contextLost,view.location]);
  const identity:BytesIdentity|null=view.artifact?{slug:view.work.slug,stage:view.stage.id,artifact_id:view.artifact.id,artifact_version:view.artifact.version,sha256:view.artifact.sha256}:null;
  return <main id="main-content" className="main reader" tabIndex={-1}>
    <nav aria-label="Breadcrumb" className="breadcrumb"><a href="/review" onClick={(event)=>{event.preventDefault();navigateLibrary();}}>Library</a><span aria-hidden="true">/</span><span aria-current="page">Read</span></nav>
    <section className="reader-title"><div><p className="eyebrow">{stageName(view.stage.id)}</p><h1>{view.work.title}</h1>{view.work.creator!=="Creator not recorded"&&<p>{view.work.creator}</p>}<button type="button" className="mode-button" onClick={openCompare} disabled={!recordedPane||!otherStage||contextLost}>Compare</button>{!otherStage&&!work.stages.some((stage)=>stage.id==="source"&&stage.availability==="selection-required")&&<p role="status">No other readable version is available to compare.</p>}</div></section>
    <SourceAuthoritySelect work={work} selectedId={view.stage.id==="source"?view.artifact?.id??null:route.right?.stage==="source"?route.right.artifact_id:null} onSelect={(artifact)=>navigateRoute(artifactRoute(work.slug,"source",artifact,view.stage.id==="source"?route.right:recordedPane))}/>
    <CandidateMemberSelect work={work} selectedId={view.stage.id==="tei"?view.artifact?.id??null:route.right?.stage==="tei"?route.right.artifact_id:null} onSelect={(artifact)=>navigateRoute(artifactRoute(work.slug,"tei",artifact,view.stage.id==="tei"?route.right:recordedPane))}/>
    {contextLost&&<div role="alert" className="drift-notice"><strong>This saved view could not be restored.</strong><span>{view.recorded_context.message}</span><span>Open the book from the Library to choose a current version.</span></div>}
    <div className="reading-layout"><StageRail work={work} selected={view.stage.id} location={view.location?.value??"start"} route={route}/><article className="artifact-panel" aria-labelledby="artifact-heading">
      <header><div><h2 id="artifact-heading">{view.location?.value==="start"?"Beginning":view.location?.label??"No readable location"}</h2></div>{view.availability!=="available"&&<Status value={view.availability}/>}</header>
      {recordedPane&&<LocationControls work={work} side="Read" view={view} onLocation={(location)=>navigateRoute(recordedStageRoute(work.slug,{...recordedPane,location},route.right))}/>}
      <SegmentControls label="Read" view={view} range={route.range} onRange={(range)=>navigateRoute(rangedStageRoute(route,range))}/>
      <LocationRangeWarning label="Read" view={view}/>
      {view.presentation?<div className="artifact-content" data-presentation-kind={view.presentation.kind} data-media-type={view.artifact?.media_type}>{renderPresentation(view.presentation,"","document",identity)}</div>:<p role="status" className="unavailable-message">{view.message}</p>}
      <footer><PresentationDetails view={view}/>{view.exact_fallback?<ExactFallbackLink fallback={view.exact_fallback}/>:contextLost&&<strong>The original file for this saved view is unavailable.</strong>}<NativeOpenControl view={view}/></footer>
    </article></div>
    <ValidationIdentity validation={work.candidate_validation} validations={work.candidate_validations}/>
  </main>;
}

interface ComparePaneControlsProps { work:ReviewWork; side:"Left"|"Right"; view:StageView; range:SegmentRange|null; onLocation:(location:string)=>void; onRange:(range:SegmentRange)=>void }

function locationIdentity(view: StageView): string {
  return JSON.stringify([
    view.work.slug,
    view.stage.id,
    view.artifact?.id ?? null,
    view.artifact?.version ?? null,
    view.artifact?.sha256 ?? null,
  ]);
}

function LocationDiscoveryControls({ work, side, view, onLocation }: { work: ReviewWork; side: "Read" | "Left" | "Right"; view: StageView; onLocation: (location: string) => void }) {
  const artifact=view.artifact;
  const artifactId=artifact?.id??null;
  const artifactVersion=artifact?.version??null;
  const artifactSha256=artifact?.sha256??null;
  const identity=locationIdentity(view);
  const [search,setSearch]=useState("");
  const [offset,setOffset]=useState(0);
  const [result,setResult]=useState<LocationDiscovery|null>(null);
  const [error,setError]=useState<string|null>(null);
  const pageSize=32;
  const textSearch=["exact-text","epub-reader"].includes(view.presentation?.kind??"");
  const discoverable=Boolean(view.outline_metadata?.truncated||(textSearch&&(view.outline_metadata?.total??view.outline.length)>0));
  useEffect(()=>{
    if(!artifactId||!artifactVersion||!discoverable)return;
    const controller=new AbortController();
    let live=true;
    setResult(null); setError(null);
    const requestSearch=search.trim()||undefined;
    loadLocations(work.slug,view.stage.id,{artifact_id:artifactId,version:artifactVersion},{offset,limit:pageSize,search:requestSearch},{signal:controller.signal})
      .then((next)=>{
        if(!live||controller.signal.aborted)return;
        const responseMatches=next.work.slug===work.slug&&next.stage.id===view.stage.id
          &&next.offset===offset&&next.limit===pageSize&&next.search===(requestSearch??null)
          &&next.artifact?.id===artifactId&&next.artifact.version===artifactVersion&&next.artifact.sha256===artifactSha256;
        if(!responseMatches){setError("Locations response did not match the requested review context.");return;}
        setResult(next);
      })
      .catch((caught:unknown)=>{
        if(!live||controller.signal.aborted||isRequestAborted(caught))return;
        setError(caught instanceof Error?caught.message:"Locations could not be loaded.");
      });
    return()=>{live=false;controller.abort();};
  },[identity,artifactId,artifactVersion,artifactSha256,offset,search,discoverable,view.stage.id,work.slug]);
  if(!discoverable)return null;
  const selected=view.location?.value??"start";
  const pageItems=result?.locations??[];
  const selectedItem=selected!=="start"&&view.location&&!pageItems.some((item)=>item.location===selected)
    ? {location:selected,label:view.location.label,level:1}
    : null;
  const options=selectedItem?[selectedItem,...pageItems]:pageItems;
  const first=offset+1;
  const last=offset+(result?.returned??0);
  const matched=result?.matched??view.outline_metadata.total;
  const total=result?.total??view.outline_metadata.total;
  return <nav aria-label={`${side} pane locations`} className="pane-locations location-discovery">
    <label>{side==="Read"?"Find a passage":`Find a passage in the ${side.toLowerCase()} pane`}<input aria-label={side==="Read"?"Find a passage":`Find a passage in the ${side.toLowerCase()} pane`} value={search} onChange={(event)=>{setSearch(boundedLocationSearch(event.target.value));setOffset(0);}} placeholder={textSearch?"Words from the source":"Chapter or heading"}/></label>
    <label>Passage<select aria-label={`${side} pane location`} disabled={view.recorded_context.state!=="exact"} value={selected} onChange={(event)=>onLocation(event.target.value)}><option value="start">Start</option>{options.map((item)=><option value={item.location} key={item.location}>{item.label}</option>)}</select></label>
    <div className="location-discovery-paging"><button type="button" onClick={()=>setOffset(Math.max(0,offset-pageSize))} disabled={offset===0}>Previous results</button><button type="button" onClick={()=>result?.next_offset!==null&&result?.next_offset!==undefined&&setOffset(result.next_offset)} disabled={!result?.next_offset}>Next results</button></div>
    <small>{error??(result?(result.returned?`Passages ${first}–${last} of ${matched} matches.`:`No passages match this search.`):"Finding passages…")}</small>
  </nav>;
}

function LocationControls({ work, side, view, onLocation }: { work:ReviewWork; side:"Read"|"Left"|"Right"; view:StageView; onLocation:(location:string)=>void }) {
  const metadata=view.outline_metadata??{available:view.presentation!==null,total:view.outline.length,returned:view.outline.length,truncated:false,complete:true};
  const showOutline=metadata.available&&(view.outline.length>0||metadata.total>0);
  return <>
    {metadata.truncated||(showOutline&&["exact-text","epub-reader"].includes(view.presentation?.kind??""))?<LocationDiscoveryControls key={locationIdentity(view)} work={work} side={side} view={view} onLocation={onLocation}/>:showOutline&&<nav aria-label={`${side} pane locations`} className="pane-locations"><label>Passage<select aria-label={`${side} pane location`} disabled={view.recorded_context.state!=="exact"} value={view.location?.value??"start"} onChange={(event)=>onLocation(event.target.value)}><option value="start">Start</option>{view.outline.map((item)=><option value={item.location} key={item.location}>{item.label}</option>)}</select></label></nav>}
  </>;
}

function ComparePaneControls({ work, side, view, range, onLocation, onRange }: ComparePaneControlsProps) {
  return <><LocationControls work={work} side={side} view={view} onLocation={onLocation}/><SegmentControls label={`${side} pane`} view={view} range={range} onRange={onRange} windowSize={1}/></>;
}

function SegmentLimitWarning({ label, view }: { label: string; view: StageView }) {
  const truncated=view.paging?.segments.some((segment)=>segment.truncated);
  const oversize=view.paging?.segments.some((segment)=>segment.oversize);
  if(!truncated&&!oversize)return null;
  return <div className="notice" role="status" aria-label={`${label} segment limit warning`}>
    {truncated?"Part of this file is missing from the view. This is not the complete text.":"This section is too large to show in full. Review is limited to the visible text."}
  </div>;
}

function ComparePane({ work, side, view, range, onLocation, onRange, focus, agentFocus, stripControls, imageRequest, imageControl, generation }: ComparePaneControlsProps & { focus:boolean; agentFocus:boolean; stripControls?:ReactNode; imageRequest:ImageRequest|null; imageControl?:ReactNode; generation:number }) {
  const contextLost=view.recorded_context.state!=="exact";
  const selectedLocation=view.location?.value??"start";
  const selectedContext=view.selected_context;
  const needsSelectedExcerpt=selectedLocation!=="start"&&selectedContext&&view.presentation
    ? !documentContainsLocation(view.presentation.document.nodes,selectedLocation)
    : false;
  useEffect(()=>{
    if(contextLost||!view.location||view.location.value==="start")return;
    const target=document.getElementById(`${side.toLowerCase()}-${view.location.value}`)
      ??document.getElementById(`${side.toLowerCase()}-selected-${view.location.value}`);
    if(target){for(let parent=target.parentElement;parent;parent=parent.parentElement){if(parent instanceof HTMLDetailsElement&&parent.classList.contains("book-details"))parent.open=true;}}
    if(focus)target?.focus({preventScroll:true}); target?.scrollIntoView?.({block:"center"});
  },[contextLost,focus,side,view.location,agentFocus]);
  const identity:BytesIdentity|null=view.artifact?{slug:view.work.slug,stage:view.stage.id,artifact_id:view.artifact.id,artifact_version:view.artifact.version,sha256:view.artifact.sha256}:null;
  const imageSelection=imageRequest||agentFocus?{...(imageRequest??{variant:"preview" as const}),scope:JSON.stringify([generation,side,selectedLocation,range])}:undefined;
  return <section className="compare-pane" aria-label={`${side} pane: ${stageName(view.stage.id)}`} data-review-side={side.toLowerCase()} data-review-stage={view.stage.id} data-artifact-id={view.artifact?.id} data-artifact-version={view.artifact?.version} data-artifact-sha256={view.artifact?.sha256} data-recorded-context={view.recorded_context.state} data-location={view.location?.value} data-location-state={view.location_state} data-segment-start={view.paging?.mode==="segments"?view.paging.segments[0]?.index:undefined} data-segment-limit={view.paging?.mode==="segments"?view.paging.segments.length:undefined}>
    <header><div className="pane-context"><h2>{stageName(view.stage.id)}</h2>{view.location?.value!=="start"&&<p className="pane-locus">{view.location?.label??"No readable location"}</p>}</div>{view.availability!=="available"&&<Status value={view.availability}/ >}{stripControls}</header>
    {contextLost&&<div role="alert" className="drift-notice" aria-label={`${side} pane recorded context warning`}><strong>The saved {side.toLowerCase()} view could not be restored.</strong><span>{view.recorded_context.message}</span><span>Open the book from the Library to choose a current version.</span></div>}
    {!agentFocus&&<><ComparePaneControls work={work} side={side} view={view} range={range} onLocation={onLocation} onRange={onRange}/>{imageRequest&&imageControl}</>}
    <LocationRangeWarning label={`${side} pane`} view={view}/>
    <SegmentLimitWarning label={`${side} pane`} view={view}/>
    {view.location_state==="page-required"&&<div className="notice" role="status" aria-label={`${side} pane loading range`}>{view.location_message??"A bounded segment range is required before this artifact can be displayed."}</div>}
    {needsSelectedExcerpt&&selectedContext&&<details className="selected-context" aria-label={`${side} pane selected location excerpt`}><summary>Selected passage: {selectedContext.label}</summary><div className="artifact-content selected-context-content">{renderPresentation({...view.presentation!,document:selectedContext.document},`${side.toLowerCase()}-selected-`,"document",identity)}</div></details>}
    {view.presentation?<article className="artifact-content" aria-label={`${side} pane artifact content`} data-presentation-kind={view.presentation.kind} data-media-type={view.artifact?.media_type}>{renderPresentation(view.presentation,`${side.toLowerCase()}-`,"document",identity,imageSelection)}</article>:<p role="status">{view.message}</p>}
    <footer hidden={agentFocus&&Boolean(view.exact_fallback)}><PresentationDetails view={view}/>{view.exact_fallback?<ExactFallbackLink fallback={view.exact_fallback}/>:contextLost&&<strong>The original file for this saved view is unavailable.</strong>}</footer>
  </section>;
}

function Compare({ work, view, route, generation, sessionControls }: { work:ReviewWork; view:CompareView; route:RouteState; generation:number; sessionControls:ReactNode }) {
  const left=route.left!; const right=route.right!;
  const [linkNotice,setLinkNotice]=useState<string|null>(null);
  const imageRequest=(side:"Left"|"Right")=>side==="Left"?route.leftImage:route.rightImage;
  const selectImageVariant=(side:"Left"|"Right",variant:"preview"|"original")=>navigateRoute(compareRoute(work.slug,left,right,route.linked,route.correspondence,route.leftRange,route.rightRange,route.agentFocus,side==="Left"?{variant}:route.leftImage,side==="Right"?{variant}:route.rightImage),side==="Left"?"left":"right");
  const imageControl=(side:"Left"|"Right",pane:StageView)=>pane.presentation?.kind==="image-facsimile"?<label>{side} image resolution<select aria-label={`${side} image resolution`} value={imageRequest(side)?.variant??(route.agentFocus?"preview":"original")} onChange={(event)=>{if(event.target.value!=="region")selectImageVariant(side,event.target.value as "preview"|"original");}}>{imageRequest(side)?.variant==="region"&&<option value="region">Exact source region</option>}<option value="preview">Preview</option><option value="original">Original resolution</option></select></label>:null;
  const focus:CompareFocus=window.history.state?.compareFocus??"left";
  const evidence=correspondenceFor(work,left,right);
  const sourceView=view.left.stage.id==="source"?view.left:view.right.stage.id==="source"?view.right:null;
  const teiView=view.left.stage.id==="tei"?view.left:view.right.stage.id==="tei"?view.right:null;
  const artifactSummary=(stage:StageId,stageView:StageView|null)=>{
    if(!stageView?.artifact)return null;
    return work.stages.find((item)=>item.id===stage)?.artifacts.find((artifact)=>artifact.id===stageView.artifact?.id&&artifact.version===stageView.artifact.version&&artifact.sha256===stageView.artifact.sha256)??null;
  };
  const pairRoute=(nextLeft:ComparePaneRequest,nextRight:ComparePaneRequest,linked:boolean,correspondence:string|null,leftRange?:SegmentRange|null,rightRange?:SegmentRange|null)=>compareRoute(work.slug,nextLeft,nextRight,linked,correspondence,leftRange,rightRange,route.agentFocus,JSON.stringify(nextLeft)===JSON.stringify(left)&&JSON.stringify(leftRange??null)===JSON.stringify(route.leftRange)?route.leftImage:null,JSON.stringify(nextRight)===JSON.stringify(right)&&JSON.stringify(rightRange??null)===JSON.stringify(route.rightRange)?route.rightImage:null);
  const toggleAgentFocus=()=>{
    navigateRoute(compareRoute(work.slug,left,right,route.linked,route.correspondence,route.leftRange,route.rightRange,!route.agentFocus,route.leftImage,route.rightImage),"none");
  };
  useEffect(()=>{
    // Restore keyboard focus when the presentation toggle replaces its own control.
    if(window.history.state?.compareFocus==="none")document.getElementById(route.agentFocus?"agent-compare-controls":"enter-agent-focus")?.focus({preventScroll:true});
  },[route.agentFocus]);
  const changeStage=(side:"left"|"right",stageId:StageId)=>{
    const stage=work.stages.find((item)=>item.id===stageId&&item.availability==="available"&&item.selected_artifact); if(!stage)return;
    const nextLeft=side==="left"?selectedPane(stage):left; const nextRight=side==="right"?selectedPane(stage):right;
    navigateRoute(pairRoute(nextLeft,nextRight,false,correspondenceFor(work,nextLeft,nextRight)?.id??null,side==="left"?null:route.leftRange,side==="right"?null:route.rightRange),side);
  };
  const changeSource=(side:"left"|"right",artifact:ArtifactSummary)=>{
    const pane:ComparePaneRequest={stage:"source",artifact_id:artifact.id,artifact_version:artifact.version,location:"start"};
    const nextLeft=side==="left"?pane:left; const nextRight=side==="right"?pane:right;
    navigateRoute(pairRoute(nextLeft,nextRight,false,correspondenceFor(work,nextLeft,nextRight)?.id??null,side==="left"?null:route.leftRange,side==="right"?null:route.rightRange),side);
  };
  const changeCandidate=(side:"left"|"right",artifact:ArtifactSummary)=>{
    const pane:ComparePaneRequest={stage:"tei",artifact_id:artifact.id,artifact_version:artifact.version,location:"start"};
    const nextLeft=side==="left"?pane:left; const nextRight=side==="right"?pane:right;
    navigateRoute(pairRoute(nextLeft,nextRight,false,correspondenceFor(work,nextLeft,nextRight)?.id??null,side==="left"?null:route.leftRange,side==="right"?null:route.rightRange),side);
  };
  const changeLeft=(location:string)=>{
    const nextLeft={...left,location}; const link=route.linked?mappedTarget(work,nextLeft,right):null;
    navigateRoute(pairRoute(nextLeft,link?{...right,location:link.location}:right,Boolean(link),correspondenceFor(work,nextLeft,right)?.id??null,null,link?null:route.rightRange),"left");
  };
  const toggleLinked=(checked:boolean)=>{
    setLinkNotice(null);
    if(!checked){navigateRoute(pairRoute(left,right,false,route.correspondence,route.leftRange,route.rightRange),"none");return;}
    const link=mappedTarget(work,left,right);
    if(!link){setLinkNotice("No matching passage is recorded for this location. The panes will move independently.");return;}
    navigateRoute(pairRoute(left,{...right,location:link.location},true,link.source,route.leftRange,route.rightRange),"right");
  };
  const readOther=right.stage!==left.stage?right:null;
  const navigation=<nav aria-label="Breadcrumb" className="breadcrumb"><a href="/review" onClick={(event)=>{event.preventDefault();navigateLibrary();}}>Library</a><span aria-hidden="true">/</span><a href={recordedStageRoute(work.slug,left,readOther)} onClick={(event)=>{event.preventDefault();navigateRoute(recordedStageRoute(work.slug,left,readOther));}}>Read</a><span aria-hidden="true">/</span><span aria-current="page">Compare</span></nav>;
  const identityControls=<><ValidationIdentity validation={work.candidate_validation} validations={work.candidate_validations}/><ReviewedIdentityControl work={work} source={artifactSummary("source",sourceView)} tei={artifactSummary("tei",teiView)} imageScope={[view.left,view.right].some((pane)=>pane.presentation?.kind==="image-facsimile")?{route:pairRoute(left,right,route.linked,route.correspondence,route.leftRange,route.rightRange),route_digest:view.route_digest??null,left:{pane:left,source_sha256:view.left.artifact?.sha256,selection:route.leftImage??{variant:route.agentFocus?"preview":"original"}},right:{pane:right,source_sha256:view.right.artifact?.sha256,selection:route.rightImage??{variant:route.agentFocus?"preview":"original"}},meaning:"Requested view scope only; derivative decode, fidelity and acceptance are not asserted."}:undefined} exact={sourceView!==null&&teiView!==null&&sourceView.recorded_context.state==="exact"&&teiView.recorded_context.state==="exact"}/></>;
  const selectionControls=<details className="artifact-selection" open={work.stages.some((stage)=>stage.artifacts.length>1)}><summary>Choose files</summary><section className="compare-controls" aria-label="Comparison controls">
      <label>Left pane<select value={left.stage} onChange={(event)=>changeStage("left",event.target.value as StageId)}>{work.stages.map((stage)=><option value={stage.id} key={stage.id} disabled={stage.availability!=="available"||!stage.selected_artifact}>{stageName(stage.id)}</option>)}</select></label>
      <label>Right pane<select value={right.stage} onChange={(event)=>changeStage("right",event.target.value as StageId)}>{work.stages.map((stage)=><option value={stage.id} key={stage.id} disabled={stage.availability!=="available"||!stage.selected_artifact}>{stageName(stage.id)}</option>)}</select></label>
      {left.stage==="source"&&(work.stages.find((stage)=>stage.id==="source")?.artifacts.length??0)>1&&<SourceArtifactPicker work={work} stage="source" artifacts={work.stages.find((stage)=>stage.id==="source")?.artifacts??[]} selectedId={left.artifact_id} onSelect={(artifact)=>changeSource("left",artifact)} filterLabel="Find a source for the left pane" selectLabel="Left source file"/>}
      {right.stage==="source"&&(work.stages.find((stage)=>stage.id==="source")?.artifacts.length??0)>1&&<SourceArtifactPicker work={work} stage="source" artifacts={work.stages.find((stage)=>stage.id==="source")?.artifacts??[]} selectedId={right.artifact_id} onSelect={(artifact)=>changeSource("right",artifact)} filterLabel="Find a source for the right pane" selectLabel="Right source file"/>}
      {left.stage==="tei"&&(work.stages.find((stage)=>stage.id==="tei")?.artifacts.length??0)>1&&<SourceArtifactPicker work={work} stage="tei" artifacts={work.stages.find((stage)=>stage.id==="tei")?.artifacts??[]} selectedId={left.artifact_id} onSelect={(artifact)=>changeCandidate("left",artifact)} filterLabel="Find a text for the left pane" selectLabel="Left text part" artifactLabel={(artifact)=>candidateArtifactLabel(work,artifact)}/>}
      {right.stage==="tei"&&(work.stages.find((stage)=>stage.id==="tei")?.artifacts.length??0)>1&&<SourceArtifactPicker work={work} stage="tei" artifacts={work.stages.find((stage)=>stage.id==="tei")?.artifacts??[]} selectedId={right.artifact_id} onSelect={(artifact)=>changeCandidate("right",artifact)} filterLabel="Find a text for the right pane" selectLabel="Right text part" artifactLabel={(artifact)=>candidateArtifactLabel(work,artifact)}/>}
      <label className="linked-control"><input type="checkbox" checked={view.linked_navigation} disabled={evidence?.state!=="known"} onChange={(event)=>toggleLinked(event.target.checked)}/>Move to matching passages together</label>
    </section></details>;
  const leftControls:ComparePaneControlsProps={work,side:"Left",view:view.left,range:route.leftRange,onLocation:changeLeft,onRange:(range)=>navigateRoute(pairRoute(left,right,route.linked,route.correspondence,range,route.rightRange),"left")};
  const rightControls:ComparePaneControlsProps={work,side:"Right",view:view.right,range:route.rightRange,onLocation:(location)=>navigateRoute(pairRoute(left,{...right,location},false,route.correspondence,route.leftRange,null),"right"),onRange:(range)=>navigateRoute(pairRoute(left,right,route.linked,route.correspondence,route.leftRange,range),"right")};
  const disclosure=<details className="agent-focus-controls">
    <summary id="agent-compare-controls">Compare controls</summary>
    <div className="agent-focus-controls-panel">
      <button type="button" className="mode-button" onClick={toggleAgentFocus}>Exit focus view</button>
      {navigation}<p>{work.title}{work.creator!=="Creator not recorded"?` · ${work.creator}`:""}</p>{selectionControls}
      {[leftControls,rightControls].map((pane)=><section key={pane.side} aria-label={`${pane.side} pane controls`}><h3>{pane.side}: {stageName(pane.view.stage.id)}</h3><ComparePaneControls {...pane}/>{imageControl(pane.side,pane.view)}{pane.view.exact_fallback&&<ExactFallbackLink fallback={pane.view.exact_fallback}/>}</section>)}
      {identityControls}{sessionControls}
    </div>
  </details>;
  return <main id="main-content" className={`main compare${route.agentFocus?" agent-focus":""}`} tabIndex={-1} data-review-state="ready" data-review-generation={generation} data-compare-route-digest={view.route_digest} data-review-route={pairRoute(left,right,route.linked,route.correspondence,route.leftRange,route.rightRange)}>
    {!route.agentFocus&&<>{navigation}<section className="reader-title"><div><p className="eyebrow">Compare</p><h1>{work.title}</h1>{work.creator!=="Creator not recorded"&&<p>{work.creator}</p>}<button type="button" id="enter-agent-focus" className="mode-button" onClick={toggleAgentFocus}>Focus view</button></div></section>{selectionControls}</>}
    {linkNotice&&<div role="status" aria-label="Linked navigation unavailable" className="notice correspondence-absent">{linkNotice}</div>}
    {view.link_refusal&&<div role="status" aria-label="Recorded linked navigation refused" className="notice correspondence-absent">{view.link_refusal}</div>}
    {(!route.agentFocus||view.correspondence.state!=="known")&&<div role="status" aria-label="Correspondence status" className={`notice correspondence-${view.correspondence.state}`}>
      <span>{view.correspondence.state==="known"?(view.linked_navigation?"Matching passages move together.":"Passage matches are available. Turn on linked navigation under Choose files."):view.correspondence.state==="uncertain"?"Passage matches are uncertain. Navigate each pane separately.":"No passage matches recorded. Navigate each pane separately."}</span>
      <details><summary>Matching details</summary><p>{view.correspondence.message}</p>{view.correspondence.source&&<p>Mapping: {view.correspondence.source}</p>}</details>
    </div>}
    <div className="compare-grid"><ComparePane {...leftControls} focus={focus==="left"} agentFocus={route.agentFocus} imageRequest={route.leftImage} imageControl={imageControl("Left",view.left)} generation={generation}/><ComparePane {...rightControls} focus={focus==="right"} agentFocus={route.agentFocus} imageRequest={route.rightImage} imageControl={imageControl("Right",view.right)} generation={generation} stripControls={route.agentFocus?<><span className="compact-correspondence" role="status" aria-label="Compact correspondence status">{view.linked_navigation?"Matching passages linked":"Independent navigation"}</span>{disclosure}</>:null}/></div>
    {!route.agentFocus&&<section className="comparison-evidence" aria-label="File details">{identityControls}</section>}
  </main>;
}

function stageMatchesRoute(view: StageView, route: RouteState): boolean {
  const requested=view.recorded_context.requested;
  const requestedFrom=view.correspondence.requested_from??null;
  const routeFrom=route.fromStage&&route.fromLocation?{stage:route.fromStage,location:route.fromLocation}:null;
  return route.slug!==null&&requested!==null&&view.work.slug===route.slug&&view.stage.id===route.stage
    && requested.artifact_id===route.artifact&&requested.version===route.version&&requested.location===route.location
    && requestedFrom?.stage===routeFrom?.stage&&requestedFrom?.location===routeFrom?.location;
}

function compareMatchesRoute(view: CompareView, route: RouteState): boolean {
  if(!route.slug||!route.left||!route.right)return false;
  const left=view.left.recorded_context.requested; const right=view.right.recorded_context.requested;
  return view.work.slug===route.slug&&view.left.stage.id===route.left.stage&&view.right.stage.id===route.right.stage
    && left?.artifact_id===route.left.artifact_id&&left.version===route.left.artifact_version&&left.location===route.left.location
    && right?.artifact_id===route.right.artifact_id&&right.version===route.right.artifact_version&&right.location===route.right.location
    && view.requested_linked_navigation===route.linked
    && JSON.stringify(view.left.image_selection??null)===JSON.stringify(route.leftImage)
    && JSON.stringify(view.right.image_selection??null)===JSON.stringify(route.rightImage);
}

export function App() {
  const [libraryQuery,setLibraryQuery]=useState("");
  const [libraryState,setLibraryState]=useState<CandidateSessionState>("all");
  const searchLibrary=(query:string,state:CandidateSessionState)=>{setLibraryQuery(query);setLibraryState(state);};
  const [route,setRoute]=useState(routeState);
  useEffect(()=>{window.scrollTo(0,0);},[route.slug,route.mode]);
  const [catalog,setCatalog]=useState<ReviewCatalog|null>(null);
  const [loadedStage,setLoadedStage]=useState<LoadedStage|null>(null);
  const [loadedCompare,setLoadedCompare]=useState<LoadedCompare|null>(null);
  const [loadedWork,setLoadedWork]=useState<LoadedWork|null>(null);
  const [workError,setWorkError]=useState<AppError|null>(null);
  const [loadingMore,setLoadingMore]=useState(false);
  const [pageError,setPageError]=useState<AppError|null>(null);
  const pageController=useRef<AbortController|null>(null);
  const compareGeneration=useRef(0);
  const [catalogError,setCatalogError]=useState<AppError|null>(null);
  const [contentError,setContentError]=useState<AppError|null>(null);
  const [catalogAttempt,setCatalogAttempt]=useState(0);
  const [contentAttempt,setContentAttempt]=useState(0);
  const [session,setSession]=useState<SessionDescriptor|null>(null);
  const [sessionLoading,setSessionLoading]=useState(true);
  const [sessionError,setSessionError]=useState<AppError|null>(null);
  const [sessionAttempt,setSessionAttempt]=useState(0);
  const workSelection:WorkSelection={};
  const panes=route.mode==="compare"?[route.left,route.right]:[route.right,{stage:route.stage,artifact_id:route.artifact,artifact_version:route.version}];
  for(const pane of panes){
    if(!pane?.artifact_id||!pane.artifact_version)continue;
    if(pane.stage==="source"){workSelection.source_artifact=pane.artifact_id;workSelection.source_version=pane.artifact_version;}
    else {workSelection.tei_artifact=pane.artifact_id;workSelection.tei_version=pane.artifact_version;}
  }
  const workKey=JSON.stringify([route.slug,workSelection,panes.map((pane)=>pane&&[pane.stage,pane.artifact_id,pane.artifact_version]),route.routeError]);
  useEffect(()=>{const update=()=>setRoute(routeState());window.addEventListener("popstate",update);return()=>window.removeEventListener("popstate",update);},[]);
  useEffect(()=>{
    let live=true; const controller=new AbortController();pageController.current?.abort();setLoadingMore(false);setPageError(null);
    const timer=window.setTimeout(()=>loadReviewCatalogPage({search:libraryQuery,state:libraryState}, {signal:controller.signal}).then((value)=>{if(live){setCatalog(value);setCatalogError(null);}}).catch((caught:unknown)=>{if(live&&!isRequestAborted(caught))setCatalogError(appError(caught));}),libraryQuery?180:0);
    return()=>{live=false;window.clearTimeout(timer);controller.abort();pageController.current?.abort();};
  },[catalogAttempt,libraryQuery,libraryState]);
  const loadMore=()=>{
    if(!catalog||catalog.page.next_offset===null||loadingMore)return;
    const previous=catalog;const controller=new AbortController();pageController.current=controller;setLoadingMore(true);setPageError(null);
    loadReviewCatalogPage({offset:previous.page.next_offset!,catalogVersion:previous.catalog_version,search:libraryQuery,state:libraryState},{signal:controller.signal})
      .then((page)=>{if(controller.signal.aborted)return;setCatalog((current)=>current===previous?{...page,works:[...previous.works,...page.works]}:current);})
      .catch((caught:unknown)=>{if(!controller.signal.aborted&&!isRequestAborted(caught))setPageError(appError(caught));})
      .finally(()=>{if(!controller.signal.aborted)setLoadingMore(false);});
  };
  useEffect(()=>{
    if(!route.slug||route.routeError){setLoadedWork(null);setWorkError(null);return;}
    let live=true;const controller=new AbortController();setWorkError(null);
    const slug=route.slug;
    const load=async()=>{
      const detail=await loadReviewWork(slug,workSelection,undefined,{signal:controller.signal});
      if(route.mode==="compare"&&route.left&&route.right&&route.left.stage===route.right.stage&&route.left.artifact_id!==route.right.artifact_id){
        const left=route.left;
        const selection:WorkSelection=left.stage==="source"?{source_artifact:left.artifact_id,source_version:left.artifact_version}:{tei_artifact:left.artifact_id,tei_version:left.artifact_version};
        const extra=await loadReviewWork(slug,selection,detail.catalog_version,{signal:controller.signal});
        detail.work.stages=detail.work.stages.map((stage)=>{
          const artifacts=[...new Map([...stage.artifacts,...(extra.work.stages.find((item)=>item.id===stage.id)?.artifacts??[])].map((item)=>[JSON.stringify([item.id,item.version]),item])).values()];
          return {...stage,artifacts,...(stage.artifact_discovery?{artifact_discovery:{...stage.artifact_discovery,returned:artifacts.length,complete:artifacts.length===stage.artifact_discovery.total}}:{})};
        });
      }
      if(live)setLoadedWork({key:workKey,work:detail.work,catalogVersion:detail.catalog_version});
    };
    load().catch((caught:unknown)=>{if(live&&!isRequestAborted(caught))setWorkError(appError(caught));});
    return()=>{live=false;controller.abort();};
  },[workKey,contentAttempt]);
  useEffect(()=>{
    let live=true; const controller=new AbortController(); setSessionLoading(true); setSessionError(null);
    loadReviewSession({signal:controller.signal}).then((value)=>{if(live){setSession(value);setSessionLoading(false);}}).catch((caught:unknown)=>{if(live&&!isRequestAborted(caught)){setSessionError(appError(caught));setSessionLoading(false);}});
    return()=>{live=false;controller.abort();};
  },[sessionAttempt]);
  useEffect(()=>{
    if(!route.slug||route.routeError||route.mode!=="read"){setLoadedStage(null);return;}
    let live=true; const controller=new AbortController(); const requested=route; setLoadedStage(null); setContentError(null);
    const from=route.fromStage&&route.fromLocation?{stage:route.fromStage,location:route.fromLocation}:undefined;
    loadStageViewAutoPaged(route.slug,route.stage,{artifact_id:route.artifact!,version:route.version!,location:route.location!},from,route.range??undefined,artifactRequestOptions(controller.signal))
      .then((view)=>{if(!stageMatchesRoute(view,requested))throw new Error("The stage response did not match the requested review context.");if(live)setLoadedStage({route:requested,view});})
      .catch((caught:unknown)=>{if(live&&!isRequestAborted(caught))setContentError(appError(caught));});
    return()=>{live=false;controller.abort();};
  },[route.slug,route.mode,route.stage,route.artifact,route.version,route.location,route.fromStage,route.fromLocation,JSON.stringify(route.right),route.range?.start,route.range?.limit,route.routeError,contentAttempt]);
  useEffect(()=>{
    if(!route.slug||route.routeError||route.mode!=="compare"||!route.left||!route.right){setLoadedCompare(null);return;}
    let live=true; const controller=new AbortController(); const requested=route; setLoadedCompare(null); setContentError(null);
    loadCompareViewAutoPaged(route.slug,route.left,route.right,route.linked,route.correspondence,route.leftRange??undefined,route.rightRange??undefined,artifactRequestOptions(controller.signal),route.leftImage,route.rightImage)
      .then((view)=>{if(!compareMatchesRoute(view,requested))throw new Error("The compare response did not match the requested review context.");if(live)setLoadedCompare({route:requested,view,generation:++compareGeneration.current});})
      .catch((caught:unknown)=>{if(live&&!isRequestAborted(caught))setContentError(appError(caught));});
    return()=>{live=false;controller.abort();};
  },[route.slug,route.mode,route.left?.stage,route.left?.artifact_id,route.left?.artifact_version,route.left?.location,route.right?.stage,route.right?.artifact_id,route.right?.artifact_version,route.right?.location,route.leftRange?.start,route.leftRange?.limit,route.rightRange?.start,route.rightRange?.limit,JSON.stringify(route.leftImage),JSON.stringify(route.rightImage),route.linked,route.correspondence,route.routeError,contentAttempt]);
  const stage=loadedStage&&sameRoute(loadedStage.route,route)?loadedStage:null;
  const compare=loadedCompare&&sameRoute(loadedCompare.route,route)?loadedCompare:null;
  const error=route.slug?(workError??contentError):catalogError;
  const errorScope=!route.slug&&catalogError?"catalog":error?"content":null;
  const work=loadedWork?.key===workKey?loadedWork.work:null;
  const loading=route.slug?(!work||!(route.mode==="read"?stage:compare)):!catalog;
  const retry=()=>{if(!route.slug){setCatalogError(null);setCatalogAttempt((value)=>value+1);}else{setWorkError(null);setContentError(null);setContentAttempt((value)=>value+1);}};
  const returnToLibrary=()=>{const reloadCatalog=!catalog||Boolean(catalogError);setCatalogError(null);setContentError(null);if(reloadCatalog)setCatalogAttempt((value)=>value+1);navigateLibrary();};
  const reviewRoute=route.mode==="compare"&&route.slug&&route.left&&route.right?compareRoute(route.slug,route.left,route.right,route.linked,route.correspondence,route.leftRange,route.rightRange,route.agentFocus,route.leftImage,route.rightImage):undefined;
  const refreshSession=()=>setSessionAttempt((value)=>value+1);
  return <Shell libraryActive={!route.slug} session={session} sessionLoading={sessionLoading} sessionError={sessionError} onRefreshSession={refreshSession} onNavigateLibrary={returnToLibrary} agentFocus={route.agentFocus&&!route.routeError}>{route.agentFocus&&(error||loading)&&<div className="focus-recovery"><button type="button" onClick={()=>navigateRoute(compareRoute(route.slug!,route.left!,route.right!,route.linked,route.correspondence,route.leftRange,route.rightRange,false,route.leftImage,route.rightImage),"none")}>Exit focus view</button></div>}{route.routeError?<main id="main-content" className="main" data-review-state="error"><div role="alert" className="error"><h1>Invalid review route</h1><p>{route.routeError}</p><button type="button" onClick={returnToLibrary}>Return to library</button></div></main>:error?<ErrorView error={error} session={session} onRetry={retry} onReturn={returnToLibrary} catalogFailure={errorScope==="catalog"} reviewRoute={reviewRoute}/>:loading?<main id="main-content" className="main loading" aria-live="polite" data-review-state="loading" data-review-route={reviewRoute}>Loading book…</main>:route.slug&&work&&compare?<Compare work={work} view={compare.view} route={route} generation={compare.generation} sessionControls={<SessionBanner session={session} loading={sessionLoading} error={sessionError} onRefresh={refreshSession}/>}/>:route.slug&&work&&stage?<Reader work={work} view={stage.view} route={stage.route}/>:<WorkList query={libraryQuery} stateFilter={libraryState} onSearch={searchLibrary} catalog={catalog!} onMore={loadMore} loadingMore={loadingMore} pageError={pageError}/>}</Shell>;
}
