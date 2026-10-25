import { createContext, createElement, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { isRequestAborted, loadNativeImage } from "./api";
import type { DocumentNode, ImageResponseMetadata, ImageRequest, NativeImageInfo, StageView } from "./types";

type PresentationMode = "document" | "selected-context";

// Ticket 06b (A1): image nodes carry no URL. The frontend composes the governed
// same-origin bytes route from its own pane identity (work slug, stage id, artifact
// id/version); node data is never trusted for addresses.
export interface BytesIdentity { slug: string; stage: string; artifact_id: string; artifact_version: string; sha256?: string }
export type ImageSelection = ImageRequest & { scope: string };
const ImageContext = createContext<{selection?: ImageSelection; info?: NativeImageInfo | null}>({});

export function stageBytesRoute(identity: BytesIdentity, download = false): string {
  const params = new URLSearchParams({expected_artifact: identity.artifact_id, expected_version: identity.artifact_version});
  if (identity.sha256) params.set("expected_sha256", identity.sha256);
  if (download) params.set("download", "1");
  return `/api/review/v1/works/${encodeURIComponent(identity.slug)}/stages/${encodeURIComponent(identity.stage)}/bytes?${params}`;
}

export function stageImageRoute(identity: BytesIdentity, selection?: ImageSelection): string {
  const params = new URLSearchParams({expected_artifact: identity.artifact_id, expected_version: identity.artifact_version,
    expected_sha256: identity.sha256 ?? "", variant: selection?.variant ?? "preview"});
  if (selection?.variant === "region") { params.set("region", selection.region); params.set("expected_sha256", selection.source_sha256); }
  return `/api/review/v1/works/${encodeURIComponent(identity.slug)}/stages/${encodeURIComponent(identity.stage)}/image?${params}`;
}

function NativeImage({identity, text, selection, info}: {identity: BytesIdentity; text: string; selection?: ImageSelection; info?: NativeImageInfo | null}) {
  const variant = selection?.variant ?? "original";
  const path = variant !== "original" ? stageImageRoute(identity, selection) : stageBytesRoute(identity);
  const [url, setUrl] = useState<string | undefined>(selection ? undefined : path);
  const [state, setState] = useState("loading");
  const [error, setError] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<ImageResponseMetadata | null>(null);
  const active = useRef(true);
  const frames = useRef<number[]>([]);
  const region = selection?.variant === "region" ? selection.region.split(",").map(Number) : null;
  const infoDimensions = region ? {width:region[2],height:region[3]} : variant === "preview" ? info?.preview : info?.normalized_dimensions;
  const dimensions = metadata?.output ?? infoDimensions;
  const previewQualifier = variant === "region" ? `Image crop ${selection?.variant === "region" ? selection.region : ""}. Use original resolution to see the full image.` : "Preview image. Use original resolution to check fine detail.";
  const quietOriginal = variant === "original" && state === "ready";
  useEffect(() => {
    active.current = true;
    const controller = new AbortController();
    let objectUrl: string | undefined;
    if (selection) {
      void loadNativeImage(path, {signal: controller.signal}).then(({blob, metadata: next}) => {
        if (!active.current || controller.signal.aborted) return;
        if (variant !== "original" && (!next || next.variant !== variant || next.source?.id !== identity.artifact_id
          || next.source?.version !== identity.artifact_version || next.source?.sha256 !== identity.sha256
          || next.source?.work !== identity.slug || next.source?.stage !== identity.stage
          || !next.output?.sha256 || next.output.bytes !== blob.size
          || (selection?.variant === "region" && (selection.source_sha256 !== identity.sha256 || next.region?.join(",") !== selection.region
            || next.output.width !== region?.[2] || next.output.height !== region?.[3] || next.transform.version !== "cvw-native-region-v1")))) {
          throw new Error("Image provenance does not match the selected artifact and image variant.");
        }
        objectUrl = URL.createObjectURL(blob);
        setMetadata(next); setUrl(objectUrl);
      }).catch((caught: unknown) => {
        if (!active.current || controller.signal.aborted || isRequestAborted(caught)) return;
        setError(caught instanceof Error ? caught.message : "The selected image could not be loaded."); setState("error");
      });
    }
    return () => {
      active.current = false; controller.abort();
      frames.current.forEach(cancelAnimationFrame);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  // Exact scope/variant changes remount this component via ImageNode's key.
  // Parent rerenders must not restart this lifecycle with stale decode work.
  }, [path]);
  const failed = () => {if (active.current) {setState("error"); setError("The selected image could not be decoded.");}};
  const loaded = async (element: HTMLImageElement) => {
    if (!active.current) return;
    setState("decoding");
    try {
      if (typeof element.decode !== "function") throw new Error("Image decode confirmation is unavailable in this browser.");
      await element.decode();
      if (!active.current || !element.isConnected) return;
      if (!element.naturalWidth || !element.naturalHeight) throw new Error("Selected image has no decoded pixels.");
      if (variant === "region" && (element.naturalWidth !== dimensions?.width || element.naturalHeight !== dimensions?.height)) throw new Error("Decoded region dimensions do not match the selected crop.");
      setState("paint-pending");
      frames.current.push(requestAnimationFrame(() => {
        frames.current.push(requestAnimationFrame(() => {if (active.current && element.isConnected) setState("ready");}));
      }));
    } catch {failed();}
  };
  return <figure className="native-image" data-image-state={state} data-image-variant={variant}
    data-image-region={selection?.variant === "region" ? selection.region : undefined} data-image-scope={selection?.scope} data-image-source-sha256={identity.sha256}
    data-image-output-sha256={metadata?.output.sha256 ?? (variant === "original" ? identity.sha256 : undefined)}
    data-image-metadata={JSON.stringify(metadata ?? info ?? null)} data-image-ready-meaning="decoded; two animation frames elapsed; visibility and fidelity not assessed">
    <figcaption className="native-image-status" role={state === "error" ? "alert" : "status"} aria-hidden={quietOriginal || undefined}>
      <span className="native-image-status-size" aria-hidden="true">{variant !== "original" ? previewQualifier : "Loading image…"}</span>
      <span className="native-image-status-text">{quietOriginal ? "" : error ?? (state === "ready" ? previewQualifier : "Loading image…")}</span>
    </figcaption>
    <div className="native-image-space" style={dimensions ? {aspectRatio: `${dimensions.width} / ${dimensions.height}`, maxWidth:dimensions.width} : undefined}>
      {url && <img src={url} width={dimensions?.width} height={dimensions?.height} loading={selection ? "eager" : "lazy"}
        alt={text} onLoad={(event) => void loaded(event.currentTarget)} onError={failed}/>}
    </div>
  </figure>;
}

function ImageNode({identity, text}: {identity: BytesIdentity; text: string}) {
  const {selection, info} = useContext(ImageContext);
  // Replacing the exact selection unmounts the old fetch/decode lifecycle before
  // it can qualify the new pane, including same-artifact navigation generations.
  const key = JSON.stringify([identity.slug, identity.stage, identity.artifact_id, identity.artifact_version,
    identity.sha256, selection?.scope, selection?.variant ?? "original", selection?.variant === "region" ? [selection.region,selection.source_sha256] : null]);
  return <NativeImage key={key} identity={identity} text={text} selection={selection} info={info}/>;
}

function nodeContent(node: DocumentNode, key: string, idPrefix: string, mode:PresentationMode, identity?:BytesIdentity|null): ReactNode {
  if (node.inline) return node.inline.map((run, index) => run.marks.reduce<ReactNode>((content, mark) => {
    const tags: Record<string,string> = {italic:"em",bold:"strong",superscript:"sup",subscript:"sub",underline:"u","small-caps":"span"};
    return createElement(tags[mark] ?? "span", {className:mark === "small-caps" ? "small-caps" : undefined},content);
  }, run.text)).map((content,index)=><span key={index}>{content}</span>);
  return node.children?.length ? node.children.map((child, index) => renderNode(child, `${key}-${index}`, idPrefix, mode, identity)) : node.text;
}

function JsonBranch({ node, nodeKey, idPrefix, mode, identity }: { node: DocumentNode; nodeKey: string; idPrefix:string; mode:PresentationMode; identity?:BytesIdentity|null }) {
  const [open, setOpen] = useState(nodeKey === "0");
  if (mode === "selected-context") return <div className="json-branch">{node.text && <p>{node.text} </p>}<ul>{node.children?.map((child, index) => renderNode(child, `${nodeKey}-${index}`, idPrefix, mode, identity))}</ul></div>;
  return <details className="json-branch" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}><summary>{node.text}</summary>{open && <ul>{node.children?.map((child, index) => renderNode(child, `${nodeKey}-${index}`, idPrefix, mode, identity))}</ul>}</details>;
}

function renderNode(node: DocumentNode, key: string, idPrefix="", mode:PresentationMode="document", identity?:BytesIdentity|null): ReactNode {
  if (node.type === "details") return <details className="book-details" key={key}><summary>{node.text}</summary><div>{node.children?.map((child,index)=>renderNode(child,`${key}-${index}`,idPrefix,mode,identity))}</div></details>;
  if (node.type === "image") return identity
    ? <ImageNode key={key} identity={identity} text={node.text}/>
    : <p key={key} role="status">{node.text}</p>;
  if (node.type === "json-value") return <span className={`json-value json-${node.value_kind}`} key={key}>{node.text}</span>;
  if (node.type === "json-property") return <li className="json-property" key={key}><span className="json-key">{node.key} </span>{nodeContent(node, key, idPrefix, mode, identity)} </li>;
  if (node.type === "json-object" || node.type === "json-array") return <JsonBranch node={node} nodeKey={key} idPrefix={idPrefix} mode={mode} identity={identity} key={key} />;
  if (node.type === "list") return createElement(node.ordered ? "ol" : "ul", {key,start:node.ordered ? node.start : undefined}, node.children?.map((child,index)=>renderNode(child,`${key}-${index}`,idPrefix,mode,identity)));
  if (node.type === "table") return <table key={key}><tbody>{node.children?.map((child,index)=>renderNode(child,`${key}-${index}`,idPrefix,mode,identity))}</tbody></table>;
  if (node.type === "table-row") return <tr key={key}>{node.children?.map((child,index)=>renderNode(child,`${key}-${index}`,idPrefix,mode,identity))}</tr>;
  if (node.type === "table-header") return <th scope={node.scope} colSpan={node.colspan} rowSpan={node.rowspan} key={key}>{nodeContent(node,key,idPrefix,mode,identity)}</th>;
  if (node.type === "table-cell") return <td colSpan={node.colspan} rowSpan={node.rowspan} key={key}>{nodeContent(node,key,idPrefix,mode,identity)}</td>;
  const content = nodeContent(node, key, idPrefix, mode, identity);
  if (node.type === "heading") {
    const level = Math.min(6, Math.max(1, node.level ?? 2));
    if (!node.text && node.location) {
      return <span className="native-location-anchor" id={`${idPrefix}${node.location}`} key={key}
        tabIndex={-1} aria-hidden="true" data-location-anchor="true" />;
    }
    return createElement(`h${level}`, { id: node.location ? `${idPrefix}${node.location}` : undefined, key, tabIndex: node.location ? -1 : undefined }, content);
  }
  if (node.type === "paragraph") return <p id={node.location ? `${idPrefix}${node.location}` : undefined}
    tabIndex={node.location ? -1 : undefined} key={key}
    style={node.align === "center" ? {textAlign: "center"} : undefined}>{content}</p>;
  if (node.type === "preformatted") return <pre key={key} id={node.location ? `${idPrefix}${node.location}` : undefined} tabIndex={node.location ? -1 : undefined}>{node.text}</pre>;
  if (node.type === "blockquote") return <blockquote key={key}>{content}</blockquote>;
  return <li key={key}>{content}</li>;
}

type Presentation = NonNullable<StageView["presentation"]>;
type PresentationRenderer = (presentation: Presentation, idPrefix?:string, mode?:PresentationMode, identity?:BytesIdentity|null) => ReactNode;
const nodeDocumentRenderer: PresentationRenderer = (presentation,idPrefix="",mode="document",identity=null) => presentation.document.nodes.map((node, index) => (
  node.type === "list-item"
    ? <ul key={String(index)}>{renderNode(node, String(index), idPrefix, mode, identity)}</ul>
    : renderNode(node, String(index), idPrefix, mode, identity)
));

function PdfPage({identity,node,idPrefix=""}: {identity:BytesIdentity;node:DocumentNode;idPrefix?:string}) {
  const [failed,setFailed]=useState(false);
  const page=node.location?.match(/^pdf-page-([1-9][0-9]*)$/)?.[1];
  if(!page)return <p>{node.text}</p>;
  const params=new URLSearchParams({expected_artifact:identity.artifact_id,expected_version:identity.artifact_version,expected_sha256:identity.sha256??"",page});
  return <figure className="pdf-page" id={node.location?`${idPrefix}${node.location}`:undefined} tabIndex={-1}><figcaption>{node.text}</figcaption>
    {failed?<p role="alert">This page could not be displayed. Download the original PDF to read it.</p>:
      <img src={`/api/review/v1/works/${encodeURIComponent(identity.slug)}/stages/${encodeURIComponent(identity.stage)}/pdf-page?${params}`} alt={`Scanned page ${page}`} onError={()=>setFailed(true)}/>}
  </figure>;
}

export const rendererRegistry: Record<string, PresentationRenderer> = {
  "sanitized-html": nodeDocumentRenderer,
  "xml-reader": nodeDocumentRenderer,
  "tei-reader": nodeDocumentRenderer,
  "sword-zld-reader": nodeDocumentRenderer,
  "barnes-zcom-reader": nodeDocumentRenderer,
  "json-tree": nodeDocumentRenderer,
  "exact-text": nodeDocumentRenderer,
  // Ticket 06b binary families: pdf-native and epub-reader emit typed inert nodes;
  // image-facsimile emits image nodes whose sources are composed at render time.
  "image-facsimile": nodeDocumentRenderer,
  "pdf-native": (presentation,idPrefix,mode,identity)=>identity
    ? presentation.document.nodes.map((node,index)=><PdfPage key={`${identity.artifact_id}-${node.location??index}`} identity={identity} node={node} idPrefix={idPrefix}/>)
    : nodeDocumentRenderer(presentation,idPrefix,mode,identity),
  "epub-reader": nodeDocumentRenderer,
};

export function renderPresentation(presentation: Presentation,idPrefix="",mode:PresentationMode="document",identity?:BytesIdentity|null,imageSelection?:ImageSelection): ReactNode {
  const renderer = rendererRegistry[presentation.kind];
  // Ticket 06b (C1): an unregistered kind degrades to the generic document renderer
  // with a visible honest label instead of throwing.
  if (!renderer) return <section className="degraded-presentation">
    <p role="status" className="degraded-message">This file is shown in a basic text view.</p>
    {nodeDocumentRenderer(presentation, idPrefix, mode, identity)}
  </section>;
  if (presentation.declared_kind === "json-tree" && presentation.kind === "exact-text") return <section className="degraded-presentation">
    <p role="status" className="degraded-message">This JSON file has no supported book layout. Its original text is shown in sections.</p>
    {renderer(presentation,idPrefix,mode,identity)}
  </section>;
  if (presentation.declared_kind === "xml-reader" && presentation.kind === "exact-text") return <section className="degraded-presentation">
    <p role="status" className="degraded-message">This XML file has no supported book layout. Its original text is shown in sections.</p>
    {renderer(presentation,idPrefix,mode,identity)}
  </section>;
  return <ImageContext.Provider value={{selection:imageSelection,info:presentation.native_image}}>
    {renderer(presentation,idPrefix,mode,identity)}
    {identity && mode === "document" && !!presentation.media_presentations?.length && <section aria-label="Retained PDF figure presentations">
      <h2>Retained PDF figure presentations</h2>
      {presentation.media_presentations.map(media => <section key={media.artifact_id}>
        <p>{media.caption}</p><p>{media.qualification}</p>
        <NativeImage identity={{...identity,stage:"source",artifact_id:media.artifact_id,artifact_version:media.artifact_version,sha256:media.sha256}} text={media.caption}/>
      </section>)}
    </section>}
  </ImageContext.Provider>;
}
