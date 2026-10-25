import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderPresentation, stageBytesRoute, stageImageRoute, type BytesIdentity } from "./renderers";
import type { ImageResponseMetadata, StageView } from "./types";

it("centers the projected align-center TEI paragraph and preserves ordinary paragraphs", () => {
  render(<>{renderPresentation({declared_kind:"tei-reader", kind:"tei-reader", render_target:"in-browser",
    document:{nodes:[{type:"paragraph",text:"Amen."},
      {type:"paragraph",text:"GRATIAS TIBI DOMINE",align:"center"}]}})}</>);
  expect(screen.getByText("GRATIAS TIBI DOMINE")).toHaveStyle({textAlign:"center"});
  expect(screen.getByText("Amen.").getAttribute("style")).toBeNull();
});

const identity: BytesIdentity = {slug:"image-work",stage:"source",artifact_id:"image-a",artifact_version:"v1",sha256:"a".repeat(64)};
it("keeps book metadata and duplicate reference text collapsed while prose is readable", async () => {
  render(<>{renderPresentation({declared_kind:"json-tree",kind:"json-tree",render_target:"in-browser",document:{nodes:[
    {type:"details",text:"About this book",children:[{type:"paragraph",text:"Descriptive metadata."}]},
    {type:"heading",level:2,text:"I. The Scriptures",location:"/Data/0/Title"},
    {type:"paragraph",text:"The actual book text."},
    {type:"details",text:"References and source notes",children:[{type:"paragraph",text:"Annotated alternative.[1]"}]},
  ]}})}</>);
  expect(screen.getByText("The actual book text.")).toBeVisible();
  expect(screen.getByText("Descriptive metadata.")).not.toBeVisible();
  expect(screen.getByText("Annotated alternative.[1]")).not.toBeVisible();
  fireEvent.click(screen.getByText("About this book"));
  expect(screen.getByText("Descriptive metadata.")).toBeVisible();
});
it("makes exact source offsets reachable without changing plain-text whitespace", () => {
  const text="A source paragraph.\r\n\r\n";
  render(<>{renderPresentation({declared_kind:"exact-text",kind:"exact-text",render_target:"in-browser",
    document:{nodes:[{type:"preformatted",text,location:"text-42"}] }},"left-")}</>);
  const paragraph=document.getElementById("left-text-42")!;
  expect(paragraph.textContent).toBe(text);
  expect(paragraph).toHaveAttribute("tabindex","-1");
});
it("automatically presents bound figures using their source identity and qualification", () => {
  const media = {artifact_id:"figure-a",artifact_version:"figure-v1",sha256:"b".repeat(64),caption:"Figure 1. Diagram.",qualification:"Retained PDF page; original TIF identity unresolved."};
  render(<>{renderPresentation({declared_kind:"tei-reader",kind:"tei-reader",render_target:"in-browser",
    document:{nodes:[{type:"paragraph",text:"Article text."}]},media_presentations:[media]},"","document",{...identity,stage:"tei"})}</>);
  expect(screen.getByRole("region",{name:"Retained PDF figure presentations"})).toBeInTheDocument();
  expect(screen.getByText(media.qualification)).toBeInTheDocument();
  const image = screen.getByRole("img");
  expect(image).toHaveAttribute("alt",media.caption);
  expect(image).toHaveAttribute("src",stageBytesRoute({...identity,artifact_id:media.artifact_id,artifact_version:media.artifact_version,sha256:media.sha256}));
});
const presentation: NonNullable<StageView["presentation"]> = {
  declared_kind:"image-facsimile",kind:"image-facsimile",render_target:"in-browser",
  document:{nodes:[{type:"image",text:"Retained source page"}]},
  native_image:{original_dimensions:{width:2400,height:1800},normalized_dimensions:{width:2400,height:1800},
    preview:{variant:"preview",width:1280,height:960,media_type:"image/png",transform_version:"cvw-native-preview-v1"}},
};
const metadata: ImageResponseMetadata = {
  ...presentation.native_image, variant:"preview",
  source:{id:"image-a",version:"v1",sha256:"a".repeat(64),work:"image-work",stage:"source",member:{root:"source",path:"page.png"},bytes:10000},
  output:{width:1280,height:960,media_type:"image/png",sha256:"b".repeat(64),bytes:4},
  transform:{version:"cvw-native-preview-v1"},
};
function response(value: ImageResponseMetadata | null = metadata): Response {
  return {ok:true,status:200,headers:new Headers(value?{"X-CVW-Image-Metadata":JSON.stringify(value)}:{}),blob:async()=>new Blob(["test"])} as Response;
}
function view(scope="document-1-left", variant:"preview"|"original"="preview", selected=identity) {
  return <>{renderPresentation(presentation,"left-","document",selected,{scope,variant})}</>;
}
function imageState() { return document.querySelector(".native-image")?.getAttribute("data-image-state"); }
let frames: FrameRequestCallback[];
beforeEach(()=>{
  frames=[];
  vi.stubGlobal("fetch",vi.fn(async()=>response()));
  vi.stubGlobal("requestAnimationFrame",vi.fn((callback:FrameRequestCallback)=>{frames.push(callback);return frames.length;}));
  vi.stubGlobal("cancelAnimationFrame",vi.fn());
  vi.stubGlobal("URL", class extends URL {static createObjectURL=vi.fn(()=>"blob:local-preview");static revokeObjectURL=vi.fn();});
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks();});

it("renders source-bound Barnes zCom slots through the normal document renderer",()=>{
  const barnes: NonNullable<StageView["presentation"]> = {
    declared_kind:"barnes-zcom-reader",kind:"barnes-zcom-reader",render_target:"in-browser",
    document:{nodes:[
      {type:"paragraph",text:"Numeric source slots only; no Bible references inferred."},
      {type:"preformatted",text:"Source slot 00004: [WARNING: invalid UTF-8; exact bytes hex: ff]"},
    ]},
  };
  render(<>{renderPresentation(barnes)}</>);
  expect(screen.getByText(/Numeric source slots only/)).toBeVisible();
  expect(screen.getByText(/Source slot 00004: \[WARNING: invalid UTF-8; exact bytes hex: ff\]/)).toBeVisible();
  expect(screen.queryByText(/No dedicated code-native viewer/)).toBeNull();
});

it("renders TEI block quotes as visible blockquote elements between prose",()=>{
  const tei: NonNullable<StageView["presentation"]> = {
    declared_kind:"tei-reader",kind:"tei-reader",render_target:"in-browser",
    document:{nodes:[
      {type:"paragraph",text:"Before"},
      {type:"blockquote",text:"",children:[
        {type:"paragraph",text:"1st, Joshua; 2nd, Judges;",inline:[
          {text:"1st, ",marks:[]}, {text:"Joshua",marks:["italic"]},
          {text:"; 2nd, Judges;",marks:[]},
        ]},
      ]},
      {type:"paragraph",text:"After"},
    ]},
  };
  const {container} = render(<>{renderPresentation(tei)}</>);
  const quote = container.querySelector("blockquote")!;
  expect(quote).toBeVisible();
  expect(quote).toHaveTextContent("1st, Joshua; 2nd, Judges;");
  expect(quote.querySelector("em")).toHaveTextContent("Joshua");
  expect(quote.previousElementSibling).toHaveTextContent("Before");
  expect(quote.nextElementSibling).toHaveTextContent("After");
});

it.each(["tei-reader", "xml-reader"] as const)("displays the %s page milestone between its neighboring headings", (kind)=>{
  const view: NonNullable<StageView["presentation"]> = {
    declared_kind:kind,kind,render_target:"in-browser",
    document:{nodes:[
      {type:"heading",text:"ANTHROPOLOGY",level:2},
      {type:"paragraph",text:"[Page break: 2]"},
      {type:"heading",text:"SYSTEMATIC THEOLOGY",level:2},
    ]},
  };
  render(<>{renderPresentation(view)}</>);
  const marker = screen.getByText("[Page break: 2]");
  expect(marker).toBeVisible();
  expect(marker.previousElementSibling).toHaveTextContent("ANTHROPOLOGY");
  expect(marker.nextElementSibling).toHaveTextContent("SYSTEMATIC THEOLOGY");
});

it("renders an empty source-native location as a neutral focus anchor",()=>{
  const xmlPresentation: NonNullable<StageView["presentation"]> = {
    declared_kind:"xml-reader",kind:"xml-reader",render_target:"in-browser",
    document:{nodes:[
      {type:"heading",text:"",level:2,location:"vi.i"},
      {type:"paragraph",text:"Readable source prose."},
    ]},
  };
  render(<>{renderPresentation(xmlPresentation,"left-","document",identity)}</>);
  const anchor=document.querySelector("[data-location-anchor]");
  expect(anchor).toHaveAttribute("id","left-vi.i");
  expect(anchor).toHaveAttribute("tabindex","-1");
  expect(anchor).toHaveAttribute("aria-hidden","true");
  expect(document.querySelector("h2")).not.toBeInTheDocument();
  expect(screen.getByText("Readable source prose.")).toBeVisible();
});

it("renders a located paragraph as a focusable navigation target",()=>{
  const tei: NonNullable<StageView["presentation"]> = {
    declared_kind:"tei-reader",kind:"tei-reader",render_target:"in-browser",
    document:{nodes:[{type:"paragraph",text:"Question 1",location:"question-one"}]},
  };
  render(<>{renderPresentation(tei,"right-")}</>);
  const paragraph=screen.getByText("Question 1");
  expect(paragraph).toHaveAttribute("id","right-question-one");
  expect(paragraph).toHaveAttribute("tabindex","-1");
});

it("forwards governed table spans and preserves explicit blank cells",()=>{
  const tablePresentation: NonNullable<StageView["presentation"]> = {
    declared_kind:"tei-reader",kind:"tei-reader",render_target:"in-browser",
    document:{nodes:[{type:"table",text:"",children:[
      {type:"table-row",text:"",children:[
        {type:"table-header",text:"",scope:"col",colspan:2},
        {type:"table-cell",text:"",rowspan:2},
      ]},
      {type:"table-row",text:"",children:[]},
    ]}]},
  };
  render(<>{renderPresentation(tablePresentation)}</>);
  const table=document.querySelector("table")!;
  expect(table.querySelectorAll("tr")).toHaveLength(2);
  expect(table.querySelectorAll("th")).toHaveLength(1);
  expect(table.querySelector("th")).toHaveAttribute("colspan","2");
  expect(table.querySelector("td")).toHaveAttribute("rowspan","2");
  expect(table.querySelectorAll("td")).toHaveLength(1);
});

it("loads only selected preview, reserves dimensions, and waits for decode plus paint frames",async()=>{
  render(view());
  expect(imageState()).toBe("loading");
  const caption=document.querySelector(".native-image-status");
  const sizer=document.querySelector(".native-image-status-size");
  expect(sizer).toHaveTextContent("Preview image. Use original resolution to check fine detail.");
  expect(document.querySelector(".native-image-space")).toHaveStyle({aspectRatio:"1280 / 960"});
  const image=await screen.findByRole("img");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(vi.mocked(fetch).mock.calls[0][0]).toBe(stageImageRoute(identity));
  expect(image).toHaveAttribute("width","1280");
  let decoded!:()=>void;
  Object.defineProperties(image,{decode:{value:()=>new Promise<void>((resolve)=>{decoded=resolve;})},naturalWidth:{value:1280},naturalHeight:{value:960}});
  fireEvent.load(image);
  expect(imageState()).toBe("decoding");
  await act(async()=>decoded());
  expect(imageState()).toBe("paint-pending");
  act(()=>frames.shift()!(0));
  expect(imageState()).toBe("paint-pending");
  act(()=>frames.shift()!(0));
  expect(imageState()).toBe("ready");
  expect(screen.getByText(/Preview image/,{selector:".native-image-status-text"})).toBeVisible();
  expect(document.querySelector(".native-image-status")).toBe(caption);
  expect(document.querySelector(".native-image-status-size")).toBe(sizer);
  expect(document.querySelector(".native-image")).toHaveAttribute("data-image-output-sha256","b".repeat(64));
});

it("switches within one renderer to original only on demand and releases the old pixels",async()=>{
  const {rerender}=render(view());
  await screen.findByRole("img");
  vi.mocked(fetch).mockResolvedValue(response(null));
  rerender(view("document-1-left","original"));
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(2));
  expect(vi.mocked(fetch).mock.calls[1][0]).toBe(stageBytesRoute(identity));
  expect(document.querySelector(".native-image")).toHaveAttribute("data-image-variant","original");
  expect(imageState()).toBe("loading");
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:local-preview");
  const caption=document.querySelector(".native-image-status");
  const sizer=document.querySelector(".native-image-status-size");
  expect(sizer).toHaveTextContent("Loading image…");
  const original=await screen.findByRole("img");
  Object.defineProperties(original,{decode:{value:async()=>{}},naturalWidth:{value:2400},naturalHeight:{value:1800}});
  fireEvent.load(original);
  await waitFor(()=>expect(imageState()).toBe("paint-pending"));
  act(()=>frames.shift()!(0));
  act(()=>frames.shift()!(0));
  expect(imageState()).toBe("ready");
  expect(document.querySelector(".native-image-status")).toBe(caption);
  expect(document.querySelector(".native-image-status-size")).toBe(sizer);
  expect(caption).toHaveAttribute("aria-hidden","true");
  expect(document.querySelector(".native-image-status-text")).toBeEmptyDOMElement();
});

it("discards both obsolete fetch and obsolete decode after a navigation generation",async()=>{
  let finishOld!:(value:Response)=>void;
  vi.mocked(fetch).mockImplementationOnce(()=>new Promise<Response>((resolve)=>{finishOld=resolve;}));
  const {rerender}=render(view("old"));
  const oldSignal=vi.mocked(fetch).mock.calls[0][1]?.signal;
  rerender(view("new"));
  const image=await screen.findByRole("img");
  await act(async()=>finishOld(response()));
  expect(oldSignal?.aborted).toBe(true);
  expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  let finishDecode!:()=>void;
  Object.defineProperties(image,{decode:{value:()=>new Promise<void>((resolve)=>{finishDecode=resolve;})},naturalWidth:{value:1280},naturalHeight:{value:960}});
  fireEvent.load(image);
  rerender(view("newer"));
  await screen.findByRole("img");
  await act(async()=>finishDecode());
  expect(imageState()).toBe("loading");
  expect(frames).toHaveLength(0);
  expect(document.querySelector(".native-image")).toHaveAttribute("data-image-scope","newer");
});

it("refuses mismatched derivative identity and makes HTTP errors visible",async()=>{
  vi.mocked(fetch).mockResolvedValueOnce(response({...metadata,source:{...metadata.source,sha256:"c".repeat(64)}}));
  const {rerender}=render(view());
  expect(await screen.findByRole("alert")).toHaveTextContent(/provenance does not match/);
  expect(screen.queryByRole("img")).toBeNull();
  vi.mocked(fetch).mockResolvedValueOnce({ok:false,status:422,headers:new Headers(),json:async()=>({error:{code:"image-too-large",message:"Native image exceeds pixel budget."}})} as Response);
  rerender(view("next"));
  expect(await screen.findByRole("alert")).toHaveTextContent(/exceeds pixel budget/);
  expect(imageState()).toBe("error");
});

it("reports decode failure rather than availability as readiness",async()=>{
  render(view());
  const image=await screen.findByRole("img");
  Object.defineProperty(image,"decode",{value:async()=>{throw new Error("bad decode");}});
  fireEvent.load(image);
  expect(await screen.findByRole("alert")).toHaveTextContent(/could not be decoded/);
  expect(imageState()).toBe("error");
});

it("keeps human original delivery lazy and does not eagerly fetch a preview",()=>{
  render(<>{renderPresentation(presentation,"","document",identity)}</>);
  expect(screen.getByRole("img")).toHaveAttribute("src",stageBytesRoute(identity));
  expect(screen.getByRole("img")).toHaveAttribute("loading","lazy");
  expect(fetch).not.toHaveBeenCalled();
});

it("binds a region response and discards a prior crop decode under the same source and scope",async()=>{
  const regionView=(region:string)=><>{renderPresentation(presentation,"left-","document",identity,{scope:"same-document-left",variant:"region",region,source_sha256:identity.sha256!})}</>;
  const regionMetadata=(region:number[]):ImageResponseMetadata=>({...metadata,variant:"region",region,output:{...metadata.output,width:region[2],height:region[3]},transform:{version:"cvw-native-region-v1"}});
  vi.mocked(fetch).mockResolvedValueOnce(response(regionMetadata([1,2,30,20]))).mockResolvedValueOnce(response(regionMetadata([10,20,4,3])));
  const {rerender}=render(regionView("1,2,30,20"));
  expect(document.querySelector(".native-image-status-size")).toHaveTextContent("Image crop 1,2,30,20. Use original resolution to see the full image.");
  const first=await screen.findByRole("img");
  expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain("region=1%2C2%2C30%2C20");
  expect(document.querySelector(".native-image-space")).toHaveStyle({aspectRatio:"30 / 20"});
  let finish!:()=>void;
  Object.defineProperties(first,{decode:{value:()=>new Promise<void>((resolve)=>{finish=resolve;})},naturalWidth:{value:30},naturalHeight:{value:20}});
  fireEvent.load(first);
  rerender(regionView("10,20,4,3"));
  const second=await screen.findByRole("img");
  const regionCaptionSizer=document.querySelector(".native-image-status-size");
  expect(regionCaptionSizer).toHaveTextContent("Image crop 10,20,4,3. Use original resolution to see the full image.");
  await act(async()=>finish());
  expect(imageState()).toBe("loading");expect(frames).toHaveLength(0);
  expect(document.querySelector(".native-image")).toHaveAttribute("data-image-region","10,20,4,3");
  Object.defineProperties(second,{decode:{value:async()=>{}},naturalWidth:{value:4},naturalHeight:{value:3}});
  fireEvent.load(second);await waitFor(()=>expect(imageState()).toBe("paint-pending"));
  expect(document.querySelector(".native-image-status-size")).toBe(regionCaptionSizer);
  act(()=>frames.shift()!(0));act(()=>frames.shift()!(0));
  expect(screen.getByText(/Image crop 10,20,4,3/,{selector:".native-image-status-text"})).toBeVisible();
  expect(imageState()).toBe("ready");
  expect(document.querySelector(".native-image-status-size")).toBe(regionCaptionSizer);
  expect(regionCaptionSizer?.textContent).toBe(document.querySelector(".native-image-status-text")?.textContent);
});

it("refuses a response for a different region even when the source hash matches",async()=>{
  vi.mocked(fetch).mockResolvedValueOnce(response({...metadata,variant:"region",region:[2,2,30,20],output:{...metadata.output,width:30,height:20},transform:{version:"cvw-native-region-v1"}}));
  render(<>{renderPresentation(presentation,"left-","document",identity,{scope:"left",variant:"region",region:"1,2,30,20",source_sha256:identity.sha256!})}</>);
  expect(await screen.findByRole("alert")).toHaveTextContent(/provenance does not match/);
  expect(screen.queryByRole("img")).toBeNull();
});


it("preserves inline emphasis and ordered multiparagraph list semantics",()=>{
  const content:NonNullable<StageView["presentation"]>={declared_kind:"tei-reader",kind:"tei-reader",render_target:"in-browser",document:{nodes:[{type:"list",text:"",ordered:true,start:4,children:[{type:"list-item",text:"",children:[{type:"paragraph",text:"A bold word",inline:[{text:"A ",marks:[]},{text:"bold",marks:["bold"]},{text:" word",marks:[]}]},{type:"paragraph",text:"Second paragraph"}]}]}]}};
  render(<>{renderPresentation(content,"test-","document",identity)}</>);
  expect(screen.getByRole("list").tagName).toBe("OL");
  expect(screen.getByRole("list")).toHaveAttribute("start","4");
  expect(screen.getAllByRole("listitem")).toHaveLength(1);
  expect(screen.getByText("bold").tagName).toBe("STRONG");
  expect(screen.getByRole("listitem").querySelectorAll("p")).toHaveLength(2);
});

it("renders scan pages through the bound PNG route and keeps an honest failure state", () => {
  render(<>{renderPresentation({declared_kind:"pdf-native",kind:"pdf-native",render_target:"in-browser",document:{nodes:[{type:"paragraph",text:"Page 12",location:"pdf-page-12"}]}},"","document",identity)}</>);
  const image=screen.getByRole("img",{name:"Scanned page 12"});
  expect(image.getAttribute("src")).toContain("expected_sha256="+identity.sha256);
  expect(image.getAttribute("src")).toContain("page=12");
  fireEvent.error(image);
  expect(screen.getByRole("alert")).toHaveTextContent("Download the original PDF");
});
