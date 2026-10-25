import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { renderPresentation } from "./renderers";
import type { CompareView, LocationDiscovery, ReviewCatalog, ReviewWork, SessionDescriptor, StageId, StageView } from "./types";

const outline = [
  {location:"start",label:"Start",level:1},
  {location:"chapter-1",label:"Chapter I",level:1},
];

const baseCatalog: ReviewCatalog = {
  contract:"ocd-corpus-review-catalog-v1",
  manifest_contract:"ocd-corpus-review-manifest-v1",
  catalog_version:"a".repeat(64),
  page:{offset:0,returned:1,total:1,next_offset:null,catalog_version:"a".repeat(64)},
  approved_roots:[{id:"retained",access:"read-only",purpose:"retained source and candidate"}],
  works:[{
    slug:"city-of-god-book-1",
    title:"The City of God — Book I",
    creator:"Augustine of Hippo",
    scope:"Retained source and validated TEI candidate",
    candidate_validation:{
      status:"pass",
      report_sha256:"dd".repeat(32),
      candidate_sha256:"aa".repeat(32),
      source_manifest_sha256:"bb".repeat(32),
    },
    stages:[
      {id:"source",label:"Retained source",availability:"available",selected_artifact:{id:"city-source",version:"v1"},artifacts:[{id:"city-source",version:"v1",name:"source.html",path:"raw/city/source.html",bytes:123,sha256:"11".repeat(32),media_type:"text/html"}],outline,message:"Selected"},
      {id:"tei",label:"Faithful TEI candidate",availability:"available",selected_artifact:{id:"city-tei",version:"v1"},artifacts:[{id:"city-tei",version:"v1",name:"content.tei.xml",path:"package/content.tei.xml",bytes:456,sha256:"22".repeat(32),media_type:"application/tei+xml"}],outline,message:"Selected"},
    ],
    correspondence_sources:[{
      id:"source-to-tei-v1",state:"known",left_stage:"source",left_artifact_id:"city-source",left_artifact_version:"v1",
      right_stage:"tei",right_artifact_id:"city-tei",right_artifact_version:"v1",
      mappings:[{left_location:"start",right_location:"start"},{left_location:"chapter-1",right_location:"chapter-1"}],
    }],
  }],
};

const baseSession: SessionDescriptor = {
  contract:"ocd-corpus-review-session-v1",
  session:{session_id:"session-1234567890",host:"127.0.0.1",requested_port:8766,port:8766,origin:"http://127.0.0.1:8766",pid:123,state:"ready",catalog_sha256:"c".repeat(64),candidate_sha256:["a".repeat(64)],implementation_sha256:"b".repeat(64),preflight_elapsed_ms:142},
};

let catalog: ReviewCatalog;
let session: SessionDescriptor;
let recordedState: StageView["recorded_context"]["state"];
let sourcePresentation: StageView["presentation"] | null;
let segmentCounts: Partial<Record<StageId, number>>;
let oversizedOutline: boolean;

function cloneCatalog(value: ReviewCatalog): ReviewCatalog {
  return JSON.parse(JSON.stringify(value)) as ReviewCatalog;
}

function stageView(stage: StageId, artifact: string, version: string, location: string, fromStage: StageId | null, fromLocation: string | null): StageView {
  const isSource=stage==="source";
  const presentation: StageView["presentation"] = stage==="source"&&sourcePresentation ? sourcePresentation : {
    declared_kind:isSource?"sanitized-html":"tei-reader",
    kind:isSource?"sanitized-html":"tei-reader",
    render_target:"in-browser" as const,
    document:{nodes:[
      {type:"heading" as const,text:isSource?"BOOK I":"Book I",level:1,location:"start"},
      {type:"paragraph" as const,text:isSource?'<img src="https://outside.invalid/probe"> The glorious city of God is my theme.':"The glorious city of God is my theme."},
      {type:"heading" as const,text:"Chapter I",level:2,location:"chapter-1"},
    ]},
  };
  const exact=recordedState==="exact";
  return {
    contract:"ocd-corpus-review-stage-view-v1",
    work:{slug:"city-of-god-book-1",title:"The City of God — Book I",creator:"Augustine of Hippo"},
    stage:{id:stage,label:isSource?"Retained source":"Faithful TEI candidate"},
    availability:"available",
    message:"Readable",
    artifact:{id:artifact,version,sha256:(isSource?"11":"22").repeat(32),media_type:isSource?"text/html":"application/tei+xml"},
    presentation,
    exact_fallback:{kind:"exact-text",target:`/exact/${stage}`,label:"Open original text"},
    native_open:{allowed:false,target:null,reason:"Rendered safely in the browser."},
    outline,
    outline_metadata:{available:true,total:stage==="tei"&&oversizedOutline?130:outline.length,returned:stage==="tei"&&oversizedOutline?0:outline.length,truncated:stage==="tei"&&oversizedOutline,complete:!(stage==="tei"&&oversizedOutline)},
    selected_context:{location,label:location==="chapter-1"?"Chapter I":"Start",text:location==="chapter-1"?"Chapter I exact context":"Start exact context",document:{nodes:[{type:"heading",text:location==="chapter-1"?"Chapter I":"Start",level:2,location}]}},
    location:{kind:"anchor",value:location,label:location==="chapter-1"?"Chapter I":"Start"},
    recorded_context:{state:recordedState,requested:{artifact_id:artifact,version,location},message:exact?"Reopened exactly.":"Recorded bytes are no longer selected."},
    correspondence:{state:fromStage?"absent":"absent",authority:null,requested_from:fromStage&&fromLocation?{stage:fromStage,location:fromLocation}:null,message:"No inferred correspondence."},
    capabilities:{read:{available:true,reason:"Readable."},compare:{available:true,reason:"Comparable."}},
  };
}

function jsonResponse(body: unknown, ok=true, status=ok?200:422): Response {
  return {ok,status,json:async()=>body} as Response;
}

function summaryResponse(query = new URLSearchParams()): Response {
  const terms=(query.get("search")??"").toLowerCase().split(/\s+/).filter(Boolean);
  const wanted=query.get("state")??"all";
  const selected=catalog.works.filter(work=>{
    if(!terms.every(term=>`${work.slug} ${work.title} ${work.creator}`.toLowerCase().includes(term)))return false;
    const source=work.stages.find(stage=>stage.id==="source");const tei=work.stages.find(stage=>stage.id==="tei");
    const state=!work.candidate_validation&&!work.candidate_validations?.length?"no-candidate":source?.availability==="unsupported"||tei?.availability==="unsupported"?"unsupported":source?.availability==="selection-required"?"choose-source":source?.availability==="available"&&tei?.availability==="available"?"available":"invalid";
    return wanted==="all"||wanted===state;
  });
  const works=selected.map((work)=>({...work,stages:work.stages.map((stage)=>({...stage,artifact_discovery:{total:stage.artifacts.length,returned:0,complete:stage.artifacts.length===0},artifacts:[],outline:[]}))}));
  return jsonResponse({...catalog,works,page:{offset:0,returned:works.length,total:works.length,next_offset:null,catalog_version:catalog.catalog_version}});
}

beforeEach(() => {
  vi.spyOn(window,"scrollTo").mockImplementation(()=>{});
  catalog=cloneCatalog(baseCatalog);
  session=JSON.parse(JSON.stringify(baseSession)) as SessionDescriptor;
  recordedState="exact";
  sourcePresentation=null;
  segmentCounts={};
  oversizedOutline=false;
  window.history.replaceState({},"","/review");
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname==="/api/review/v1/session")return jsonResponse(session);
    if(url.pathname==="/api/review/v1/works")return summaryResponse(url.searchParams);
    const workMatch=url.pathname.match(/^\/api\/review\/v1\/works\/([^/]+)$/);
    if(workMatch)return jsonResponse({contract:"ocd-corpus-review-work-v1",catalog_version:catalog.catalog_version,work:catalog.works.find((work)=>work.slug===decodeURIComponent(workMatch[1]))});
    const locationsMatch=url.pathname.match(/^\/api\/review\/v1\/works\/city-of-god-book-1\/stages\/(source|tei)\/locations$/);
    if(locationsMatch){
      const stage=locationsMatch[1] as StageId;
      const search=url.searchParams.get("search");
      const locations=search
        ? [{location:"filtered",label:"Filtered Part",level:1}]
        : [{location:"part-1",label:"Part One",level:1}];
      return jsonResponse({
        contract:"ocd-corpus-review-locations-v1",work:{slug:"city-of-god-book-1",title:"The City of God — Book I",creator:"Augustine of Hippo"},
        stage:{id:stage,label:stage==="source"?"Retained source":"Faithful TEI candidate"},availability:"available",message:"Locations loaded.",
        artifact:{id:url.searchParams.get("expected_artifact"),version:url.searchParams.get("expected_version"),sha256:stage==="source"?"11".repeat(32):"22".repeat(32)},
        search,offset:Number(url.searchParams.get("offset")),limit:Number(url.searchParams.get("limit")),total:130,matched:search?1:130,returned:locations.length,next_offset:search?null:Number(url.searchParams.get("offset"))+locations.length,complete:false,locations,
      });
    }
    const stageMatch=url.pathname.match(/^\/api\/review\/v1\/works\/city-of-god-book-1\/stages\/(source|tei|json)$/);
    if(stageMatch){
      const stage=stageMatch[1] as StageId;
      const view=stageView(stage,url.searchParams.get("expected_artifact")!,url.searchParams.get("expected_version")!,url.searchParams.get("location")!,url.searchParams.get("from_stage") as StageId|null,url.searchParams.get("from_location"));
      return jsonResponse(applyPaging(view,url.searchParams.get("segment_start"),url.searchParams.get("segment_limit")));
    }
    if(url.pathname.endsWith("/compare")){
      const pane=(side:"left"|"right")=>applyPaging(stageView(
        url.searchParams.get(`${side}_stage`) as StageId,
        url.searchParams.get(`${side}_artifact`)!,
        url.searchParams.get(`${side}_version`)!,
        url.searchParams.get(`${side}_location`)!,
        null,null,
      ),url.searchParams.get(`${side}_segment_start`),url.searchParams.get(`${side}_segment_limit`));
      const correspondence=url.searchParams.get("correspondence");
      const known=correspondence!=="absent";
      const linked=url.searchParams.get("linked")==="true"&&known;
      const left=pane("left"); const right=pane("right");
      for(const [side,view] of [["left",left],["right",right]] as const) {
        const region=url.searchParams.get(`${side}_region`), variant=url.searchParams.get(`${side}_image`);
        if(region)view.image_selection={variant:"region",region,source_sha256:url.searchParams.get(`${side}_image_sha256`)!};
        else if(variant)view.image_selection={variant:variant as "preview"|"original"};
      }
      const result:CompareView={
        contract:"ocd-corpus-review-compare-view-v1",work:left.work,left,right,
        requested_linked_navigation:url.searchParams.get("linked")==="true",linked_navigation:linked,link_refusal:null,
        correspondence:{state:known?"known":"absent",source:known?correspondence:null,left_stage:left.stage.id,right_stage:right.stage.id,left_location:left.location!.value,right_location:known?right.location!.value:null,message:known?"Explicit candidate mapping loaded.":"No correspondence evidence was supplied."},
      };
      return jsonResponse(result);
    }
    return jsonResponse({error:{message:`Unexpected request: ${url.pathname}`}},false);
  }));
});

function applyPaging(view: StageView, startText: string | null, limitText: string | null): StageView {
  const count=segmentCounts[view.stage.id];
  if(!count)return view;
  view.paging={
    mode:"segments",max_segments_per_request:8,segment_count:count,
    segments:Array.from({length:count},(_,index)=>({index,scalar_count:100,locations:index===0?["start"]:index===4?["chapter-1"]:[]})),
    location_segment:view.location?.value==="chapter-1"?4:0,
    bound:{artifact_id:view.artifact!.id,version:view.artifact!.version,sha256:view.artifact!.sha256},
    cache_resident:true,
  };
  if(startText===null||limitText===null){
    view.location_state="page-required";
    view.location_message="Choose a bounded segment range.";
    view.presentation=null;
    return view;
  }
  const start=Number(startText); const limit=Number(limitText);
  const target=view.location?.value==="chapter-1"?4:0;
  const includesLocation=target>=start&&target<start+limit;
  view.location_state=includesLocation?"in-range":"location-outside-range";
  view.location_message=includesLocation
    ? "Requested location is inside the served segment range."
    : "The recorded location lies outside the requested segment range; neighboring content was not substituted and no replacement was inferred.";
  view.presentation={
    declared_kind:view.stage.id==="source"?"sanitized-html":"tei-reader",
    kind:view.stage.id==="source"?"sanitized-html":"tei-reader",
    render_target:"in-browser",
    document:{nodes:[{type:"paragraph",text:`${view.stage.label} segments ${start+1}-${start+limit}`}]},
  };
  view.paging.segments=view.paging.segments.slice(start,start+limit);
  return view;
}

afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks();});

const comparePath="/review/works/city-of-god-book-1?mode=compare&leftStage=source&leftArtifact=city-source&leftVersion=v1&leftLocation=start&rightStage=tei&rightArtifact=city-tei&rightVersion=v1&rightLocation=start&linked=false&correspondence=source-to-tei-v1";
const readPath="/review/works/city-of-god-book-1?stage=source&artifact=city-source&version=v1&location=start";

it.each(["%20","a".repeat(257)])("rejects malformed work slug %s before artifact dispatch",async(slug)=>{
  window.history.replaceState({},"",readPath.replace("city-of-god-book-1",slug));
  render(<App/>);
  expect(await screen.findByRole("heading",{name:"Invalid review route"})).toBeVisible();
  expect(vi.mocked(fetch).mock.calls.some(([input])=>String(input).includes("/stages/")||String(input).includes("/compare"))).toBe(false);
});

it("loads another Library page using the first page's catalog version",async()=>{
  const current=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname!=="/api/review/v1/works")return current(input,init);
    const offset=Number(url.searchParams.get("offset"));
    if(offset===1)expect(url.searchParams.get("catalog_version")).toBe(catalog.catalog_version);
    return jsonResponse({...catalog,works:[offset===0?catalog.works[0]:{...catalog.works[0],slug:"second-work",title:"Second work"}],page:{offset,returned:1,total:2,next_offset:offset===0?1:null,catalog_version:catalog.catalog_version}});
  });
  const user=userEvent.setup();render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Load more books"}));
  expect(await screen.findByText("Second work")).toBeVisible();
  expect(screen.getByText(/Showing 2 of 2/)).toBeVisible();
});

it("selects a discovered source beyond the initial 50 and reopens its exact identity",async()=>{
  window.history.replaceState({},"",readPath);
  const source=catalog.works[0].stages[0];
  const first=source.artifacts[0];
  source.artifacts=[first,...Array.from({length:49},(_,index)=>({...first,id:`source-${index}`,name:`member-${index}`,path:`raw/member-${index}`}))];
  source.artifact_discovery={total:61,returned:50,complete:false};
  catalog.works[0].approved_roots_discovery={route:"/api/review/v1/roots",total:61,page_size:50,catalog_version:catalog.catalog_version};
  const late={...first,id:"late-source",name:"late member",path:"raw/late-member",candidate_validation_tei_artifact_id:"city-tei"};
  const current=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname.endsWith("/stages/source/artifacts")){
      const searched=Boolean(url.searchParams.get("search"));const artifacts=searched?[late]:source.artifacts;
      return jsonResponse({contract:"ocd-corpus-review-artifacts-v1",catalog_version:catalog.catalog_version,artifacts,total:61,matched:searched?1:61,page:{offset:0,returned:artifacts.length,total:searched?1:61,next_offset:searched?null:50}});
    }
    if(url.pathname==="/api/review/v1/works/city-of-god-book-1"&&url.searchParams.get("source_artifact")==="late-source"){
      const work=cloneCatalog(catalog).works[0];work.stages[0].artifacts.push(late);work.stages[0].artifact_discovery!.returned=51;
      return jsonResponse({contract:"ocd-corpus-review-work-v1",catalog_version:catalog.catalog_version,work});
    }
    return current(input,init);
  });
  const user=userEvent.setup();render(<App/>);
  await user.type(await screen.findByRole("searchbox",{name:"Source file search"}),"late");
  const option=await screen.findByRole("option",{name:"late member — raw/late-member"});
  await user.selectOptions(screen.getByRole("combobox",{name:"Source file"}),option);
  await waitFor(()=>expect(new URLSearchParams(window.location.search).get("artifact")).toBe("late-source"));
  await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(([input])=>String(input).includes("source_artifact=late-source&source_version=v1"))).toBe(true));
  await user.click(screen.getByText("File details",{selector:"summary"}));
  expect(await screen.findByText("late member",{selector:"strong"})).toBeVisible();
});

it("uses the governed collection count when one source record was returned",async()=>{
  const source=catalog.works[0].stages[0];
  source.availability="selection-required";
  source.selected_artifact=null;
  source.artifact_discovery={total:61,returned:1,complete:false};
  window.history.replaceState({},"","/review/works/city-of-god-book-1?stage=tei&artifact=city-tei&version=v1&location=start");
  render(<App/>);
  expect(await screen.findByText("Choose one of the 61 source files to read.")).toBeVisible();
  expect(screen.getByRole("combobox",{name:"Source file"})).toBeVisible();
});

it("keeps two distinct opaque identities when both Compare panes use source artifacts",async()=>{
  window.history.replaceState({},"",comparePath.replace("leftArtifact=city-source&leftVersion=v1","leftArtifact=a%3Ab&leftVersion=c").replace("rightStage=tei&rightArtifact=city-tei&rightVersion=v1","rightStage=source&rightArtifact=a&rightVersion=b%3Ac"));
  const first=catalog.works[0].stages[0].artifacts[0];
  const choices=[{...first,id:"a:b",version:"c",name:"Left source"},{...first,id:"a",version:"b:c",name:"Right source"}];
  const current=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname==="/api/review/v1/works/city-of-god-book-1"){
      const work=cloneCatalog(catalog).works[0];const selected=choices.find((item)=>item.id===url.searchParams.get("source_artifact"))!;
      work.stages[0].artifacts=[selected];work.stages[0].selected_artifact={id:selected.id,version:selected.version};work.stages[0].artifact_discovery={total:2,returned:1,complete:false};
      return jsonResponse({contract:"ocd-corpus-review-work-v1",catalog_version:catalog.catalog_version,work});
    }
    return current(input,init);
  });
  render(<App/>);
  const left=await screen.findByRole("combobox",{name:"Left source file"});
  expect(left).toHaveValue("a:b");
  expect(screen.getByRole("combobox",{name:"Right source file"})).toHaveValue("a");
  expect(within(left).getAllByRole("option")).toHaveLength(2);
});

it("loads an exact direct Read route without waiting for the bounded Library summary",async()=>{
  window.history.replaceState({},"",readPath);
  const current=vi.mocked(fetch).getMockImplementation()!;
  let releaseSummary!:(response:Response)=>void;
  const heldSummary=new Promise<Response>((resolve)=>{releaseSummary=resolve;});
  const detail={contract:"ocd-corpus-review-work-v1",catalog_version:"a".repeat(64),work:catalog.works[0]};
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname==="/api/review/v1/works")return heldSummary;
    if(url.pathname==="/api/review/v1/works/city-of-god-book-1")return jsonResponse(detail);
    return current(input,init);
  });
  render(<App/>);
  await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(([input])=>String(input).includes("/api/review/v1/works/city-of-god-book-1?") || String(input).endsWith("/api/review/v1/works/city-of-god-book-1"))).toBe(true));
  await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(([input])=>String(input).includes("/stages/source"))).toBe(true));
  expect(vi.mocked(fetch).mock.calls.some(([input])=>String(input).includes("view=summary"))).toBe(true);
  releaseSummary(summaryResponse());
});

it.each([
  ["Read",readPath,"/stages/"],
  ["Compare",comparePath,"/compare"],
] as const)("loads direct %s artifacts while the Library summary is pending",async(_mode,path,artifactPath)=>{
  window.history.replaceState({},"",path);
  const current=vi.mocked(fetch).getMockImplementation()!;
  let releaseCatalog!:(response:Response)=>void;
  const heldCatalog=new Promise<Response>((resolve)=>{releaseCatalog=resolve;});
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname==="/api/review/v1/works")return heldCatalog;
    return current(input,init);
  });
  render(<App/>);
  await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(([input])=>String(input).includes("/api/review/v1/works"))).toBe(true));
  await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(([input])=>String(input).includes(artifactPath))).toBe(true));
  releaseCatalog(summaryResponse());
});

it("keeps direct Compare usable when the Library summary fails",async()=>{
  window.history.replaceState({},"",comparePath);
  const current=vi.mocked(fetch).getMockImplementation()!;
  let compareRequests=0;
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname==="/api/review/v1/works")return jsonResponse({error:{code:"catalog-unavailable",message:"Catalog unavailable."}},false,503);
    if(url.pathname.endsWith("/compare"))compareRequests+=1;
    return current(input,init);
  });
  render(<App/>);
  expect(await screen.findByRole("article",{name:"Left pane artifact content"})).toBeVisible();
  expect(compareRequests).toBe(1);
});

it("retries exact work details after failure without silently choosing a different work",async()=>{
  window.history.replaceState({},"",comparePath);
  const current=vi.mocked(fetch).getMockImplementation()!;
  let catalogAttempts=0;
  let compareRequests=0;
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname==="/api/review/v1/works/city-of-god-book-1"){
      catalogAttempts+=1;
      if(catalogAttempts===1)return jsonResponse({error:{code:"catalog-unavailable",message:"Catalog unavailable."}},false,503);
    }
    if(url.pathname.endsWith("/compare"))compareRequests+=1;
    return current(input,init);
  });
  const user=userEvent.setup(); render(<App/>);
  expect(await screen.findByRole("heading",{name:"Artifact unavailable"})).toBeVisible();
  expect(compareRequests).toBe(1);
  await user.click(screen.getByRole("button",{name:"Try again"}));
  expect(await screen.findByRole("article",{name:"Left pane artifact content"})).toBeVisible();
  expect(catalogAttempts).toBe(2);
  expect(compareRequests).toBe(2);
});

it("keeps direct Compare usable after session failure and does not refetch it on session refresh",async()=>{
  window.history.replaceState({},"",comparePath);
  const current=vi.mocked(fetch).getMockImplementation()!;
  let sessionAttempts=0;
  let compareRequests=0;
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname==="/api/review/v1/session"){
      sessionAttempts+=1;
      if(sessionAttempts===1)return jsonResponse({error:{code:"session-unavailable",message:"Session unavailable."}},false,500);
    }
    if(url.pathname.endsWith("/compare"))compareRequests+=1;
    return current(input,init);
  });
  const user=userEvent.setup(); render(<App/>);
  expect(await screen.findByRole("article",{name:"Left pane artifact content"})).toBeVisible();
  expect(screen.getByText("Session unavailable.",{selector:"p"})).toBeVisible();
  expect(compareRequests).toBe(1);
  await user.click(screen.getByText("Session details",{selector:"summary"}));
  await user.click(screen.getByRole("button",{name:"Refresh session"}));
  await waitFor(()=>expect(sessionAttempts).toBe(2));
  expect(compareRequests).toBe(1);
  expect(screen.getByRole("article",{name:"Left pane artifact content"})).toBeVisible();
});

it("toggles optional agent focus without refetching or replacing either artifact rendering",async()=>{
  window.history.replaceState({},"",comparePath);
  const user=userEvent.setup(); render(<App/>);
  const enter=await screen.findByRole("button",{name:"Focus view"});
  const left=screen.getByRole("article",{name:"Left pane artifact content"});
  const right=screen.getByRole("article",{name:"Right pane artifact content"});
  const content=[left.innerHTML,right.innerHTML];
  const generation=screen.getByRole("main").getAttribute("data-review-generation");
  const requests=vi.mocked(fetch).mock.calls.length;
  expect(screen.getByRole("heading",{name:"The City of God — Book I"})).toBeVisible();
  expect(screen.getByRole("region",{name:"Comparison controls"})).not.toBeVisible();
  await user.click(screen.getByText("Choose files",{selector:"summary"}));
  expect(screen.getByRole("region",{name:"Comparison controls"})).toBeVisible();
  await user.click(enter);
  expect(window.location.search).toContain("focus=agent");
  expect(screen.getByRole("main")).toHaveClass("agent-focus");
  expect(screen.getByRole("main")).toHaveAttribute("data-review-generation",generation);
  expect(screen.getByRole("main")).toHaveAttribute("data-review-route",window.location.pathname+window.location.search);
  expect(screen.getByRole("article",{name:"Left pane artifact content"})).toBe(left);
  expect(screen.getByRole("article",{name:"Right pane artifact content"})).toBe(right);
  expect([left.innerHTML,right.innerHTML]).toEqual(content);
  expect(vi.mocked(fetch).mock.calls).toHaveLength(requests);
  expect(screen.queryByRole("heading",{name:"The City of God — Book I"})).not.toBeInTheDocument();
  const summary=screen.getByText("Compare controls",{selector:"summary"});
  expect(summary).toHaveFocus();
  expect(summary.closest("details")).not.toHaveAttribute("open");
  expect(screen.getByRole("combobox",{name:"Right pane location"})).not.toBeVisible();
  // jsdom does not implement native summary keyboard activation; browser QA covers it.
  await user.click(summary);
  expect(summary.closest("details")).toHaveAttribute("open");
  expect(screen.getByRole("combobox",{name:"Left pane location"})).toBeVisible();
  expect(screen.getByRole("combobox",{name:"Right pane location"})).toBeVisible();
  const exit=screen.getByRole("button",{name:"Exit focus view"});
  exit.focus(); await user.keyboard("{Enter}");
  expect(window.location.search).not.toContain("focus=");
  expect(screen.getByRole("button",{name:"Focus view"})).toHaveFocus();
  expect(screen.getByRole("article",{name:"Left pane artifact content"})).toBe(left);
  expect(screen.getByRole("article",{name:"Right pane artifact content"})).toBe(right);
});

it("discovers an oversized outline with bounded search and preserves the selected location",async()=>{
  oversizedOutline=true;
  const teiPath=comparePath
    .replace("leftStage=source&leftArtifact=city-source&leftVersion=v1&leftLocation=start","leftStage=tei&leftArtifact=city-tei&leftVersion=v1&leftLocation=chapter-1")
    .replace("rightStage=tei&rightArtifact=city-tei&rightVersion=v1&rightLocation=start","rightStage=source&rightArtifact=city-source&rightVersion=v1&rightLocation=start");
  window.history.replaceState({},"",teiPath);
  const user=userEvent.setup(); render(<App/>);
  const search=await screen.findByRole("textbox",{name:"Find a passage in the left pane"});
  const locations=screen.getByRole("combobox",{name:"Left pane location"});
  expect(locations).toHaveValue("chapter-1");
  expect(within(locations).getByRole("option",{name:"Chapter I"})).toBeInTheDocument();
  await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(([input])=>String(input).includes("/locations?"))).toBe(true));
  await user.type(search,"filtered");
  await waitFor(()=>expect(screen.getByText(/1 matches/)).toBeVisible());
  expect(new URL(String(vi.mocked(fetch).mock.calls.at(-1)?.[0]),"http://localhost").searchParams.get("search")).toBe("filtered");
  expect(within(locations).getByRole("option",{name:"Chapter I"})).toBeInTheDocument();
  await user.click(screen.getByRole("button",{name:"Focus view"}));
  await user.click(screen.getByText("Compare controls",{selector:"summary"}));
  expect(within(screen.getByRole("region",{name:"Left pane controls"})).getByRole("textbox",{name:"Find a passage in the left pane"})).toBeVisible();
});

it("bounds astral location search input before requesting the discovery endpoint",async()=>{
  oversizedOutline=true;
  const teiPath=comparePath
    .replace("leftStage=source&leftArtifact=city-source&leftVersion=v1&leftLocation=start","leftStage=tei&leftArtifact=city-tei&leftVersion=v1&leftLocation=chapter-1")
    .replace("rightStage=tei&rightArtifact=city-tei&rightVersion=v1&rightLocation=start","rightStage=source&rightArtifact=city-source&rightVersion=v1&rightLocation=start");
  window.history.replaceState({},"",teiPath);
  render(<App/>);
  const search=await screen.findByRole("textbox",{name:"Find a passage in the left pane"});
  const bounded="𝔘".repeat(256);
  fireEvent.change(search,{target:{value:"𝔘".repeat(257)}});
  await waitFor(()=>expect(search).toHaveValue(bounded));
  await waitFor(()=>expect(new URL(String(vi.mocked(fetch).mock.calls.at(-1)?.[0]),"http://localhost").searchParams.get("search")).toBe(bounded));
  expect(screen.queryByText("Locations response did not match the requested review context.")).not.toBeInTheDocument();
});

it("fails closed when a location response changes its bound work identity",async()=>{
  oversizedOutline=true;
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const response=await original(input,init);
    if(String(input).includes("/locations?")){
      const body=await response.json() as LocationDiscovery;
      return jsonResponse({...body,work:{...body.work,slug:"different-work"}});
    }
    return response;
  });
  const teiPath=comparePath
    .replace("leftStage=source&leftArtifact=city-source&leftVersion=v1&leftLocation=start","leftStage=tei&leftArtifact=city-tei&leftVersion=v1&leftLocation=chapter-1")
    .replace("rightStage=tei&rightArtifact=city-tei&rightVersion=v1&rightLocation=start","rightStage=source&rightArtifact=city-source&rightVersion=v1&rightLocation=start");
  window.history.replaceState({},"",teiPath);
  render(<App/>);
  expect(await screen.findByText("Locations response did not match the requested review context.")).toBeVisible();
  expect(screen.getByRole("combobox",{name:"Left pane location"})).toHaveValue("chapter-1");
});

it.each(["focus=agent&focus=agent","focus=human","focus=true","focus=","focus=Agent","focus=agent&extra=true"])("rejects invalid Compare focus query %s before artifact dispatch",async(query)=>{
  window.history.replaceState({},"",`${comparePath}&${query}`); render(<App/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid review route");
  expect(vi.mocked(fetch).mock.calls.some(([input])=>String(input).includes("/compare"))).toBe(false);
});

it.each(["/review?focus=agent","/review/works/city-of-god-book-1?stage=source&artifact=city-source&version=v1&location=start&focus=agent"])("rejects focus outside Compare: %s",async(path)=>{
  window.history.replaceState({},"",path); render(<App/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("focus");
  expect(vi.mocked(fetch).mock.calls.some(([input])=>String(input).includes("/stages/"))).toBe(false);
});

it("restores agent focus, independent locations and ranges through reload and browser history",async()=>{
  segmentCounts={source:18,tei:10};
  const path=`${comparePath.replace("leftLocation=start","leftLocation=chapter-1")}&leftSegmentStart=4&leftSegmentLimit=1&rightSegmentStart=2&rightSegmentLimit=1&focus=agent`;
  window.history.replaceState({},"",path);
  const user=userEvent.setup(); render(<App/>);
  await screen.findByRole("article",{name:"Left pane artifact content"});
  expect(screen.getByRole("main")).toHaveClass("agent-focus");
  expect(screen.getByRole("region",{name:"Left pane: Source"})).toHaveAttribute("data-segment-start","4");
  await user.click(screen.getByText("Compare controls",{selector:"summary"}));
  await user.click(within(screen.getByRole("navigation",{name:"Right pane segment navigation"})).getByRole("button",{name:"Next section"}));
  expect(await screen.findByText("Faithful TEI candidate segments 4-4")).toBeVisible();
  expect(window.location.search).toContain("leftLocation=chapter-1");
  expect(window.location.search).toContain("leftSegmentStart=4");
  expect(window.location.search).toContain("rightSegmentStart=3");
  expect(window.location.search).toContain("focus=agent");
  cleanup(); render(<App/>);
  expect(await screen.findByText("Faithful TEI candidate segments 4-4")).toBeVisible();
  expect(screen.getByRole("main")).toHaveClass("agent-focus");
  await user.click(screen.getByText("Compare controls",{selector:"summary"}));
  await user.click(screen.getByRole("button",{name:"Exit focus view"}));
  window.history.back();
  await waitFor(()=>expect(screen.getByRole("main")).toHaveClass("agent-focus"));
  expect(screen.getByText("Faithful TEI candidate segments 4-4")).toBeVisible();
  window.history.back();
  expect(await screen.findByText("Faithful TEI candidate segments 3-3")).toBeVisible();
  expect(window.location.search).toContain("focus=agent");
  window.history.forward();
  expect(await screen.findByText("Faithful TEI candidate segments 4-4")).toBeVisible();
  expect(window.location.search).toContain("leftLocation=chapter-1");
});

it("keeps agent focus and the other pane range through location, artifact, and retained-source changes",async()=>{
  segmentCounts={source:18,tei:10};
  const source=catalog.works[0].stages[0];
  source.artifacts.push({...source.artifacts[0],id:"city-source-two",name:"second.html"});
  window.history.replaceState({},"",`${comparePath}&leftSegmentStart=2&leftSegmentLimit=1&rightSegmentStart=3&rightSegmentLimit=1&focus=agent`);
  const user=userEvent.setup(); render(<App/>);
  await screen.findByRole("article",{name:"Right pane artifact content"});
  await user.click(screen.getByText("Compare controls",{selector:"summary"}));
  await user.selectOptions(screen.getByRole("combobox",{name:"Right pane location"}),"chapter-1");
  expect(await screen.findByText("Faithful TEI candidate segments 5-5")).toBeVisible();
  expect(window.location.search).toContain("leftSegmentStart=2");
  expect(window.location.search).toContain("focus=agent");
  await user.click(screen.getByText("Compare controls",{selector:"summary"}));
  await user.selectOptions(screen.getByRole("combobox",{name:"Left source file"}),"city-source-two");
  await waitFor(()=>expect(screen.getByRole("region",{name:"Left pane: Source"})).toHaveAttribute("data-artifact-id","city-source-two"));
  expect(window.location.search).toContain("rightLocation=chapter-1");
  expect(window.location.search).toContain("focus=agent");
  await user.click(screen.getByText("Compare controls",{selector:"summary"}));
  await user.selectOptions(screen.getByRole("combobox",{name:"Left pane"}),"tei");
  await waitFor(()=>expect(screen.getByRole("region",{name:"Left pane: Reconstructed text"})).toHaveAttribute("data-artifact-id","city-tei"));
  expect(window.location.search).toContain("rightLocation=chapter-1");
  expect(window.location.search).toContain("focus=agent");
});

it("keeps absent correspondence, range and truncated-segment warnings visible outside closed focus controls",async()=>{
  segmentCounts={tei:10};
  const current=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(...args)=>{
    const response=await current(...args);
    if(!String(args[0]).includes("/compare"))return response;
    const result=await response.json() as CompareView;
    result.right.paging!.segments[0].truncated=true;
    result.right.paging!.segments[0].oversize=true;
    return jsonResponse(result);
  });
  window.history.replaceState({},"",`${comparePath.replace("correspondence=source-to-tei-v1","correspondence=absent")}&rightSegmentStart=2&rightSegmentLimit=1&focus=agent`);
  render(<App/>);
  expect(await screen.findByRole("status",{name:"Right pane segment limit warning"})).toHaveTextContent("Part of this file is missing from the view.");
  expect(screen.getByRole("status",{name:"Right pane recorded location warning"})).toBeVisible();
  expect(screen.getByRole("status",{name:"Correspondence status"})).toHaveTextContent("Navigate each pane separately.");
  expect(screen.getByRole("status",{name:"Compact correspondence status"})).toHaveTextContent("Independent navigation");
  expect(screen.getByText("Compare controls",{selector:"summary"}).closest("details")).not.toHaveAttribute("open");
});

it("retains drift, unsupported content, refused correspondence and session warnings in focus",async()=>{
  recordedState="drift";
  session.session.state="failed"; session.session.error_message="Runtime diagnostic failure.";
  const current=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(...args)=>{
    const response=await current(...args);
    if(!String(args[0]).includes("/compare"))return response;
    const result=await response.json() as CompareView;
    result.left.availability="unsupported"; result.left.presentation=null; result.left.message="Source presentation is unsupported.";
    result.link_refusal="Recorded link is unavailable.";
    result.correspondence.state="uncertain"; result.correspondence.message="The mapping is uncertain.";
    return jsonResponse(result);
  });
  window.history.replaceState({},"",`${comparePath}&focus=agent`); render(<App/>);
  expect(await screen.findByText("Source presentation is unsupported.")).toBeVisible();
  expect(screen.getByRole("alert",{name:"Left pane recorded context warning"})).toBeVisible();
  expect(screen.getByRole("status",{name:"Recorded linked navigation refused"})).toBeVisible();
  expect(screen.getByRole("status",{name:"Correspondence status"})).toHaveTextContent("uncertain");
  expect(screen.getByRole("status",{name:"Session warning"})).toHaveTextContent("Runtime diagnostic failure.");
  expect(within(screen.getByRole("region",{name:"Left pane: Source"})).getByText("Unsupported")).toBeVisible();
});

it("exposes loading and error states without a committed generation and keeps a focus exit",async()=>{
  const current=vi.mocked(fetch).getMockImplementation()!;
  let complete!:(response:Response)=>void;
  vi.mocked(fetch).mockImplementation(async(...args)=>String(args[0]).includes("/compare")?new Promise<Response>((resolve)=>{complete=resolve;}):current(...args));
  window.history.replaceState({},"",`${comparePath}&focus=agent`);
  const user=userEvent.setup(); render(<App/>);
  await waitFor(()=>expect(complete).toBeDefined());
  expect(screen.getByRole("main")).toHaveAttribute("data-review-state","loading");
  expect(screen.getByRole("main")).not.toHaveAttribute("data-review-generation");
  expect(screen.getByRole("button",{name:"Exit focus view"})).toBeVisible();
  complete(jsonResponse({error:{code:"context-unavailable",message:"Exact pair unavailable."}},false));
  expect(await screen.findByRole("alert")).toHaveTextContent("Exact pair unavailable.");
  expect(screen.getByRole("main")).toHaveAttribute("data-review-state","error");
  expect(screen.getByRole("main")).not.toHaveAttribute("data-review-generation");
  await user.click(screen.getByRole("button",{name:"Exit focus view"}));
  expect(window.location.search).not.toContain("focus=");
  expect(screen.getByRole("alert")).toBeVisible();
});

it("shows the minimal Library with retained source and TEI candidate only", async()=>{
  render(<App/>);
  expect(await screen.findByRole("heading",{name:"Library"})).toBeVisible();
  expect(screen.getByRole("columnheader",{name:"Book"})).toBeVisible();
  expect(screen.getByRole("columnheader",{name:"Status"})).toBeVisible();
  expect(screen.queryByText(/structure/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/notes/i)).not.toBeInTheDocument();
});

it("shows the current session identity and copies bounded session diagnostics", async()=>{
  const user=userEvent.setup(); render(<App/>);
  const banner=await screen.findByRole("region",{name:"CVW session diagnostics"});
  expect(banner).toHaveTextContent("ready · session-1234…");
  expect(banner).toHaveTextContent("http://127.0.0.1:8766");
  await user.click(within(banner).getByText("Session details",{selector:"summary"}));
  await user.click(within(banner).getByRole("button",{name:"Copy session details"}));
  expect(await screen.findByText("Session details copied.")).toBeVisible();
  expect(JSON.parse(await navigator.clipboard.readText())).toEqual({contract:"ocd-cvw-session-diagnostics-v1",session:baseSession.session});
});

it("keeps diagnostic actions collapsed while session failures stay visible",async()=>{
  const current=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL,init?:RequestInit)=>{
    if(new URL(String(input),"http://localhost").pathname==="/api/review/v1/session")return jsonResponse({error:{message:"Session diagnostics unavailable."}},false,500);
    return current(input,init);
  });
  const user=userEvent.setup();render(<App/>);
  expect(await screen.findByText("Session diagnostics unavailable.",{selector:"p"})).toBeVisible();
  expect(screen.getByRole("button",{name:"Refresh session"})).not.toBeVisible();
  await user.click(screen.getByText("Session details",{selector:"summary"}));
  expect(screen.getByRole("button",{name:"Refresh session"})).toBeVisible();
  expect(screen.getByRole("heading",{name:"Library"})).toBeVisible();
});

it("marks Library current only while browsing and names the active breadcrumb",async()=>{
  const user=userEvent.setup();render(<App/>);
  const library=within(await screen.findByRole("complementary",{name:"Review navigation"})).getByRole("link",{name:"Library"});
  expect(library).toHaveAttribute("aria-current","page");
  vi.mocked(window.scrollTo).mockClear();
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  await screen.findByRole("button",{name:"Compare"});
  expect(window.scrollTo).toHaveBeenCalledWith(0,0);
  expect(library).not.toHaveAttribute("aria-current");
  expect(within(screen.getByRole("navigation",{name:"Breadcrumb"})).getByText("Read")).toHaveAttribute("aria-current","page");
  await user.click(screen.getByRole("button",{name:"Compare"}));
  await screen.findByRole("heading",{name:"The City of God — Book I"});
  expect(library).not.toHaveAttribute("aria-current");
  expect(within(screen.getByRole("navigation",{name:"Breadcrumb"})).getByText("Compare")).toHaveAttribute("aria-current","page");
});

it("keeps the last session identity visible when a diagnostics refresh fails", async()=>{
  const current=vi.mocked(fetch).getMockImplementation()!;
  let sessionAttempts=0;
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname==="/api/review/v1/session"&&sessionAttempts++===1)return jsonResponse({error:{code:"session-unavailable",message:"Session endpoint temporarily unavailable."}},false,500);
    return current(input);
  });
  const user=userEvent.setup(); render(<App/>);
  const banner=await screen.findByRole("region",{name:"CVW session diagnostics"});
  expect(await within(banner).findByText("ready · session-1234…")).not.toBeVisible();
  await user.click(within(banner).getByText("Session details",{selector:"summary"}));
  await user.click(within(banner).getByRole("button",{name:"Refresh session"}));
  expect(await within(banner).findByText("Could not refresh session details: Session endpoint temporarily unavailable.")).toBeVisible();
  expect(banner).toHaveTextContent("http://127.0.0.1:8766");
});

it("does not retry a received HTTP failure and recovers through the explicit retry action", async()=>{
  const current=vi.mocked(fetch).getMockImplementation()!;
  let catalogAttempts=0;
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname==="/api/review/v1/works"&&catalogAttempts++===0)return jsonResponse({error:{code:"temporary",message:"Temporary service failure."}},false,503);
    return current(input);
  });
  const user=userEvent.setup(); render(<App/>);
  expect(await screen.findByRole("heading",{name:"Review unavailable"})).toBeVisible();
  expect(catalogAttempts).toBe(1);
  await user.click(screen.getByRole("button",{name:"Try again"}));
  expect(await screen.findByRole("heading",{name:"Library"})).toBeVisible();
  expect(catalogAttempts).toBe(2);
});

it("returns to the Library after a catalog failure instead of retaining the error screen", async()=>{
  const current=vi.mocked(fetch).getMockImplementation()!;
  let catalogAttempts=0;
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname==="/api/review/v1/works"&&catalogAttempts++===0)return jsonResponse({error:{code:"catalog-unavailable",message:"Catalog unavailable."}},false,500);
    return current(input);
  });
  const user=userEvent.setup(); render(<App/>);
  expect(await screen.findByRole("heading",{name:"Review unavailable"})).toBeVisible();
  await user.click(screen.getByRole("button",{name:"Return to library"}));
  expect(await screen.findByRole("heading",{name:"Library"})).toBeVisible();
  expect(catalogAttempts).toBe(2);
});

it("shows request diagnostics and supports a read-only recovery handoff", async()=>{
  const current=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname==="/api/review/v1/works")return jsonResponse({error:{code:"artifact-unavailable",message:"The candidate bytes could not be read.",request_id:"request-123"}},false,500);
    return current(input);
  });
  const user=userEvent.setup(); render(<App/>);
  expect(await screen.findByRole("heading",{name:"Review unavailable"})).toBeVisible();
  expect(screen.getByText("artifact-unavailable",{selector:"code"})).toBeVisible();
  expect(screen.getByText("request-123",{selector:"code"})).toBeVisible();
  await user.click(screen.getByRole("button",{name:"Copy error details"}));
  expect(await screen.findByText("Error details copied.")).toBeVisible();
  const diagnostics=JSON.parse(await navigator.clipboard.readText());
  expect(diagnostics.error).toMatchObject({code:"artifact-unavailable",request_id:"request-123",status:500,path:"/api/review/v1/works?view=summary&offset=0&limit=50"});
  expect(diagnostics.session.session_id).toBe(baseSession.session.session_id);
});

it("filters the Library without changing its underlying state", async()=>{
  const user=userEvent.setup(); render(<App/>);
  const search=await screen.findByRole("searchbox",{name:"Search books"});
  await user.type(search,"Spurgeon");
  expect(await screen.findByText(/No books match these filters/)).toBeVisible();
  await user.clear(search); await user.type(search,"Augustine");
  expect(await screen.findAllByText("The City of God — Book I")).toHaveLength(1);
});

it("clears both Library filters after an empty result without changing candidate identity",async()=>{
  const user=userEvent.setup();render(<App/>);
  const search=await screen.findByRole("searchbox",{name:"Search books"});
  await user.selectOptions(screen.getByRole("combobox",{name:"Show"}),"no-candidate");
  await user.type(search,"Spurgeon");
  expect(await screen.findByText(/No books match/)).toBeVisible();
  await user.click(screen.getByRole("button",{name:"Clear filters"}));
  expect(search).toHaveValue("");
  expect(screen.getByRole("combobox",{name:"Show"})).toHaveValue("all");
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  await screen.findByRole("button",{name:"Compare"});
  expect(window.location.search).toContain("artifact=city-source&version=v1");
});

it("labels the bounded exact-text fallback for a large JSON authority", async()=>{
  sourcePresentation={
    declared_kind:"json-tree",
    kind:"exact-text",
    render_target:"in-browser",
    document:{nodes:[{type:"preformatted",text:'{"translation":"DRC"}'}]},
  };
  const user=userEvent.setup(); render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  expect(await screen.findByRole("status",{name:""})).toHaveTextContent(
    "This JSON file has no supported book layout. Its original text is shown in sections."
  );
  expect(screen.getByText('{"translation":"DRC"}')).toBeVisible();
});

it.each(["exact-text","epub-reader"] as const)("offers %s source search even when every passage fits in the initial outline",async(kind)=>{
  sourcePresentation={declared_kind:kind,kind,render_target:"in-browser",
    document:{nodes:[{type:"preformatted",text:"The glorious city of God.",location:"chapter-1"}]}};
  const user=userEvent.setup();render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  const search=await screen.findByRole("textbox",{name:"Find a passage"});
  expect(search).toHaveAttribute("placeholder","Words from the source");
  await user.type(search,"glorious");
  expect(await screen.findByRole("option",{name:"Filtered Part"})).toBeInTheDocument();
  await user.selectOptions(screen.getByRole("combobox",{name:"Read pane location"}),"filtered");
  await waitFor(()=>expect(window.location.search).toContain("location=filtered"));
});

it("triages compact candidate session states and combines title and creator terms", async()=>{
  const makeWork=(slug:string,title:string):ReviewWork=>({...cloneCatalog(baseCatalog).works[0],slug,title});
  const available=makeWork("available","Available Work");
  const missing=makeWork("missing","Missing Candidate Work"); missing.candidate_validation=null; missing.stages=missing.stages.map((stage)=>({...stage,availability:"unavailable",selected_artifact:null,artifacts:[],message:"No artifact is declared for this stage."}));
  const choose=makeWork("choose","Choose Source Work"); choose.stages[0]={...choose.stages[0],availability:"selection-required",selected_artifact:null};
  const unsupported=makeWork("unsupported","Unsupported Work"); unsupported.stages[0]={...unsupported.stages[0],availability:"unsupported"};
  const invalid=makeWork("invalid","Invalid Work"); invalid.stages[1]={...invalid.stages[1],availability:"unavailable",selected_artifact:null};
  catalog.works=[available,missing,choose,unsupported,invalid];
  const user=userEvent.setup(); render(<App/>);
  expect(await screen.findByText("Showing 5 of 5")).toBeVisible();
  expect(screen.getByText("Not loaded",{selector:"span.session-state"})).toBeVisible();
  expect(screen.getByText("Choose a source",{selector:"span.session-state"})).toBeVisible();
  expect(screen.getByText("Source needs download",{selector:"span.session-state"})).toBeVisible();
  expect(screen.getByText("Needs attention",{selector:"span.session-state"})).toBeVisible();
  await user.selectOptions(screen.getByRole("combobox",{name:"Show"}),"no-candidate");
  expect(screen.getByText("Showing 1 of 1")).toBeVisible();
  expect(screen.getByText("Missing Candidate Work")).toBeVisible();
  await user.selectOptions(screen.getByRole("combobox",{name:"Show"}),"all");
  await user.type(screen.getByRole("searchbox",{name:"Search books"}),"Augustine available");
  expect(screen.getByText("Available Work")).toBeVisible();
  await waitFor(()=>expect(screen.queryByText("Missing Candidate Work")).not.toBeInTheDocument());
});

it("reads retained source as inert typed content and exposes exact access", async()=>{
  const user=userEvent.setup(); render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  expect(await screen.findByText('<img src="https://outside.invalid/probe"> The glorious city of God is my theme.')).toBeVisible();
  expect(document.querySelector(".artifact-content img")).toBeNull();
  expect(screen.getByRole("link",{name:"Open original text"})).toHaveAttribute("href","/exact/source");
  expect(screen.queryByText(/notes for this work/i)).not.toBeInTheDocument();
});

it("opens a passage directly in Read and keeps that exact selection in Compare",async()=>{
  const user=userEvent.setup();render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  const before=new URLSearchParams(window.location.search);
  await user.selectOptions(await screen.findByRole("combobox",{name:"Read pane location"}),"chapter-1");
  await waitFor(()=>expect(new URLSearchParams(window.location.search).get("location")).toBe("chapter-1"));
  expect(new URLSearchParams(window.location.search).get("artifact")).toBe(before.get("artifact"));
  expect(new URLSearchParams(window.location.search).get("version")).toBe(before.get("version"));
  await user.click(screen.getByRole("button",{name:"Compare"}));
  await waitFor(()=>expect(screen.getByRole("main")).toHaveAttribute("data-review-state","ready"));
  expect(new URLSearchParams(window.location.search).get("leftLocation")).toBe("chapter-1");
});

it("pages every bounded Read segment while preserving exact artifact identity", async()=>{
  segmentCounts={source:18};
  const user=userEvent.setup(); render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  const controls=await screen.findByRole("navigation",{name:"Read segment navigation"});
  expect(controls).toHaveTextContent("Sections 1–8 of 18");
  expect(screen.getByText("Retained source segments 1-8")).toBeVisible();
  await user.click(within(controls).getByRole("button",{name:"Next section"}));
  expect(await screen.findByText("Retained source segments 9-16")).toBeVisible();
  expect(screen.getByRole("status",{name:"Read recorded location warning"})).toHaveTextContent("no replacement was inferred");
  expect(window.location.search).toContain("segmentStart=8");
  expect(window.location.search).toContain("segmentLimit=8");
  await user.click(within(screen.getByRole("navigation",{name:"Read segment navigation"})).getByRole("button",{name:"Next section"}));
  expect(await screen.findByText("Retained source segments 17-18")).toBeVisible();
  const last=screen.getByRole("navigation",{name:"Read segment navigation"});
  expect(last).toHaveTextContent("Sections 17–18 of 18");
  expect(within(last).getByRole("button",{name:"Next section"})).toBeDisabled();
  const stageRequests=vi.mocked(fetch).mock.calls.map(([input])=>new URL(String(input),"http://localhost")).filter((url)=>url.pathname.includes("/stages/source"));
  expect(stageRequests.filter((url)=>url.searchParams.has("segment_limit")).every((url)=>Number(url.searchParams.get("segment_limit"))<=8)).toBe(true);
  expect(stageRequests.every((url)=>url.searchParams.get("expected_artifact")==="city-source"&&url.searchParams.get("expected_version")==="v1")).toBe(true);
});

it("pages the two Compare panes independently", async()=>{
  segmentCounts={source:18,tei:10};
  const user=userEvent.setup(); render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  await user.click(await screen.findByRole("button",{name:"Compare"}));
  const left=await screen.findByRole("navigation",{name:"Left pane segment navigation"});
  const right=screen.getByRole("navigation",{name:"Right pane segment navigation"});
  expect(left).toHaveTextContent("Sections 1–1 of 18");
  expect(right).toHaveTextContent("Sections 1–1 of 10");
  await user.click(within(right).getByRole("button",{name:"Next section"}));
  expect(await screen.findByText("Faithful TEI candidate segments 2-2")).toBeVisible();
  expect(screen.getByRole("status",{name:"Right pane recorded location warning"})).toHaveTextContent("no replacement was inferred");
  expect(screen.getByText("Retained source segments 1-1")).toBeVisible();
  expect(window.location.search).toContain("rightSegmentStart=1");
  expect(window.location.search).not.toContain("leftSegmentStart=1");
  await user.click(within(screen.getByRole("navigation",{name:"Left pane segment navigation"})).getByRole("button",{name:"Next section"}));
  expect(await screen.findByText("Retained source segments 2-2")).toBeVisible();
  expect(screen.getByRole("status",{name:"Left pane recorded location warning"})).toHaveTextContent("no replacement was inferred");
  expect(screen.getByText("Faithful TEI candidate segments 2-2")).toBeVisible();
  expect(window.location.search).toContain("leftSegmentStart=1");
  expect(window.location.search).toContain("rightSegmentStart=1");
});

it("moves a paged Compare pane to the segment containing a selected recorded location", async()=>{
  segmentCounts={tei:10};
  const user=userEvent.setup(); render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  await user.click(await screen.findByRole("button",{name:"Compare"}));
  const right=await screen.findByRole("region",{name:"Right pane: Reconstructed text"});
  await user.selectOptions(within(right).getByRole("combobox",{name:"Right pane location"}),"chapter-1");
  const controls=await screen.findByRole("navigation",{name:"Right pane segment navigation"});
  expect(controls).toHaveTextContent("Sections 5–5 of 10");
  expect(await screen.findByText("Faithful TEI candidate segments 5-5")).toBeVisible();
  await user.click(screen.getByText("Selected passage: Chapter I"));
  expect(screen.getByText("Selected passage: Chapter I").closest("details")).toHaveAttribute("open");
  expect(screen.queryByRole("status",{name:"Right pane recorded location warning"})).not.toBeInTheDocument();
  const compareRequests=vi.mocked(fetch).mock.calls.map(([input])=>new URL(String(input),"http://localhost")).filter((url)=>url.pathname.endsWith("/compare")&&url.searchParams.get("right_location")==="chapter-1");
  expect(compareRequests.some((url)=>url.searchParams.get("right_segment_start")==="4"&&url.searchParams.get("right_segment_limit")==="1")).toBe(true);
});

it("keeps the selected passage in view when entering Focus view",async()=>{
  window.history.replaceState({compareFocus:"none"},"",comparePath.replace("rightLocation=start","rightLocation=chapter-1"));
  const user=userEvent.setup();render(<App/>);
  const right=await screen.findByRole("region",{name:"Right pane: Reconstructed text"});
  const target=await within(right).findByRole("heading",{name:"Chapter I"});
  const scroll=vi.fn();target.scrollIntoView=scroll;
  await user.click(screen.getByRole("button",{name:"Focus view"}));
  await waitFor(()=>expect(scroll).toHaveBeenCalledWith({block:"center"}));
});

it("requires an explicit Paradise-style source choice and offers every manifest member in order", async()=>{
  const source=catalog.works[0].stages.find((stage)=>stage.id==="source")!;
  source.availability="selection-required";
  source.selected_artifact=null;
  source.message="Choose a retained source. Multiple manifest-bound authorities are available; the viewer will not guess.";
  source.artifacts=[
    {id:"paradise-license",version:"license-v1",name:"source-001",path:"raw/standard_ebooks/john-milton_paradise-lost/LICENSE.md",bytes:561,sha256:"33".repeat(32),media_type:"text/markdown"},
    {id:"paradise-book-1",version:"book-v1",name:"source-018",path:"raw/standard_ebooks/john-milton_paradise-lost/src/epub/text/book-1.xhtml",bytes:61973,sha256:"44".repeat(32),media_type:"application/xhtml+xml"},
  ];
  catalog.works[0].correspondence_sources=[];
  const user=userEvent.setup(); render(<App/>);
  expect(await screen.findByText("Choose a source",{selector:"span.session-state"})).toBeVisible();
  await user.click(screen.getByRole("button",{name:"Open The City of God — Book I"}));
  const chooser=await screen.findByRole("combobox",{name:"Source file"});
  expect(screen.queryByText("No other readable version is available to compare.")).not.toBeInTheDocument();
  expect(within(chooser).getAllByRole("option").map((option)=>option.textContent)).toEqual([
    "Choose a source",
    "source-001 — raw/standard_ebooks/john-milton_paradise-lost/LICENSE.md",
    "source-018 — raw/standard_ebooks/john-milton_paradise-lost/src/epub/text/book-1.xhtml",
  ]);
  expect(chooser).toHaveValue("");
  expect(screen.getByText(/Choose one of the 2 source files to read/)).toBeVisible();
  await user.selectOptions(chooser,"paradise-book-1");
  await user.click(screen.getByText("File details",{selector:"summary"}));
  expect(await screen.findByText("source-018",{selector:"strong"})).toBeVisible();
  expect(window.location.search).toContain("artifact=paradise-book-1");
  expect(window.location.search).not.toContain("paradise-license");
  await user.click(screen.getByRole("button",{name:"Compare"}));
  const compareChooser=await screen.findByRole("combobox",{name:"Left source file"});
  expect(compareChooser).toHaveValue("paradise-book-1");
  await user.selectOptions(compareChooser,"paradise-license");
  await waitFor(()=>expect(window.location.search).toContain("leftArtifact=paradise-license"));
  expect(screen.queryByRole("button",{name:/accept|publish/i})).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.every(([,init])=>!init||init.method===undefined||init.method==="GET")).toBe(true);
});

it("shows the exact validated candidate identity in Read and Compare", async()=>{
  const user=userEvent.setup(); render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  let identity=await screen.findByRole("status",{name:"Candidate validation identity"});
  expect(identity).toHaveTextContent("Automated checks passed for this review copy.");
  expect(identity).toHaveTextContent("This viewer does not record approval or publication decisions.");
  expect(identity).toHaveTextContent("dddddddddddd…");
  expect(identity).toHaveTextContent("aaaaaaaaaaaa…");
  expect(identity).toHaveTextContent("bbbbbbbbbbbb…");
  expect(within(identity).getByTitle("dd".repeat(32))).not.toBeVisible();
  await user.click(within(identity).getByText("Validation details",{selector:"summary"}));
  expect(within(identity).getByTitle("dd".repeat(32))).toBeVisible();
  await user.click(screen.getByRole("button",{name:"Compare"}));
  identity=await screen.findByRole("status",{name:"Candidate validation identity"});
  expect(identity).toHaveTextContent("Automated checks passed for this review copy.");
});

it("keeps a chosen source through version switches, passage changes, paging, reload, and Compare",async()=>{
  const source=catalog.works[0].stages.find((stage)=>stage.id==="source")!;
  source.selected_artifact=null;source.availability="selection-required";
  source.artifacts=[{...source.artifacts[0],id:"book-1",version:"book-v1",name:"Book I"},
    {...source.artifacts[0],id:"book-12",version:"book-v12",name:"Book XII"}];
  catalog.works[0].correspondence_sources=[];
  segmentCounts.tei=20;
  const fetchDefault=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname==="/api/review/v1/works/city-of-god-book-1"&&url.searchParams.has("source_artifact")){
      const work=cloneCatalog(catalog).works[0];
      const selected=work.stages.find((stage)=>stage.id==="source")!;
      selected.availability="available";
      selected.selected_artifact={id:url.searchParams.get("source_artifact")!,version:url.searchParams.get("source_version")!};
      return jsonResponse({contract:"ocd-corpus-review-work-v1",catalog_version:catalog.catalog_version,work});
    }
    return fetchDefault(input,init);
  });
  const user=userEvent.setup();const mounted=render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  await user.selectOptions(await screen.findByRole("combobox",{name:"Source file"}),"book-12");
  await user.click(await screen.findByRole("button",{name:"Reconstructed text"}));
  await user.selectOptions(await screen.findByRole("combobox",{name:"Read pane location"}),"chapter-1");
  expect(await screen.findByRole("combobox",{name:"Source file"})).toHaveValue("book-12");
  expect(await screen.findByRole("button",{name:"Compare"})).toBeEnabled();
  await user.click(screen.getByRole("button",{name:"Next section"}));
  await waitFor(()=>expect(window.location.search).toContain("segmentStart="));
  expect(window.location.search).toContain("rightArtifact=book-12&rightVersion=book-v12");
  mounted.unmount();render(<App/>);
  expect(await screen.findByRole("combobox",{name:"Source file"})).toHaveValue("book-12");
  await user.click(screen.getByRole("button",{name:"Compare"}));
  expect(await screen.findByRole("combobox",{name:"Right source file"})).toHaveValue("book-12");
  expect(window.location.search).toContain("leftLocation=chapter-1");
  await user.click(screen.getByRole("link",{name:"Read"}));
  expect(await screen.findByRole("button",{name:"Compare"})).toBeEnabled();
  await user.click(screen.getByRole("button",{name:"Source"}));
  expect(await screen.findByRole("combobox",{name:"Source file"})).toHaveValue("book-12");
});

it.each([
  "rightStage=source&rightArtifact=book-12",
  "rightStage=tei&rightArtifact=book-12&rightVersion=v1&rightLocation=start",
])("rejects an incomplete or same-stage remembered reading version: %s",async(other)=>{
  window.history.replaceState({},"","/review/works/city-of-god-book-1?stage=tei&artifact=city-tei&version=v1&location=start&"+other);
  render(<App/>);
  expect(await screen.findByRole("heading",{name:"Invalid review route"})).toBeVisible();
});

it("exposes every Equiano candidate member and refuses a mismatched reviewed pair", async()=>{
  const multi=cloneCatalog(baseCatalog).works[0];
  multi.title="The Interesting Narrative of the Life of Olaudah Equiano";
  multi.candidate_validation=null;
  multi.candidate_validations=[
    {status:"pass",report_sha256:"d1".repeat(32),candidate_sha256:"a1".repeat(32),source_manifest_sha256:"b1".repeat(32),source_id:"ecco-tcp-k053415-001-pinned-ets",source_artifact_ids:["equiano-source-1"],tei_artifact_id:"equiano-tei-1"},
    {status:"pass",report_sha256:"d2".repeat(32),candidate_sha256:"a2".repeat(32),source_manifest_sha256:"b2".repeat(32),source_id:"ecco-tcp-k053415-002-pinned-ets",source_artifact_ids:["equiano-source-2"],tei_artifact_id:"equiano-tei-2"},
  ];
  const source=multi.stages.find((stage)=>stage.id==="source")!;
  source.availability="selection-required";
  source.selected_artifact=null;
  source.message="Choose one exact retained source authority.";
  source.artifacts=[
    {id:"equiano-source-1",version:"source-v1",name:"part-1.xml",path:"raw/equiano/part-1.xml",bytes:101,sha256:"11".repeat(32),media_type:"text/xml"},
    {id:"equiano-source-2",version:"source-v2",name:"part-2.xml",path:"raw/equiano/part-2.xml",bytes:102,sha256:"11".repeat(32),media_type:"text/xml"},
  ];
  const tei=multi.stages.find((stage)=>stage.id==="tei")!;
  tei.selected_artifact={id:"equiano-tei-1",version:"tei-v1"};
  tei.artifacts=[
    {id:"equiano-tei-1",version:"tei-v1",name:"content.tei.xml",path:"part-1/package/content.tei.xml",bytes:201,sha256:"22".repeat(32),media_type:"application/tei+xml"},
    {id:"equiano-tei-2",version:"tei-v2",name:"content.tei.xml",path:"part-2/package/content.tei.xml",bytes:202,sha256:"22".repeat(32),media_type:"application/tei+xml"},
  ];
  catalog.works=[multi];
  const user=userEvent.setup(); render(<App/>);
  await user.click(await screen.findByRole("button",{name:/Open The Interesting Narrative/}));
  const candidatePicker=await screen.findByRole("combobox",{name:"Text part"});
  expect(candidatePicker).toHaveValue("equiano-tei-1");
  expect(within(candidatePicker).getAllByRole("option").map((option)=>option.textContent)).toEqual([
    "Choose a text part",
    "ecco-tcp-k053415-001-pinned-ets — content.tei.xml — part-1/package/content.tei.xml",
    "ecco-tcp-k053415-002-pinned-ets — content.tei.xml — part-2/package/content.tei.xml",
  ]);
  await user.selectOptions(candidatePicker,"equiano-tei-2");
  expect(window.location.search).toContain("artifact=equiano-tei-2");

  window.history.replaceState({},"", "/review/works/city-of-god-book-1?mode=compare&leftStage=source&leftArtifact=equiano-source-1&leftVersion=source-v1&leftLocation=start&rightStage=tei&rightArtifact=equiano-tei-2&rightVersion=tei-v2&rightLocation=start&linked=false&correspondence=absent");
  window.dispatchEvent(new PopStateEvent("popstate"));
  const copy=await screen.findByRole("button",{name:"Copy comparison details"});
  expect(copy).toBeDisabled();
  expect(screen.getByText("This source does not belong to the selected text. Choose a matching pair.")).toBeVisible();
  await user.selectOptions(await screen.findByRole("combobox",{name:"Left source file"}),"equiano-source-2");
  expect(await screen.findByRole("button",{name:"Copy comparison details"})).toBeEnabled();
  expect(window.location.search).toContain("leftArtifact=equiano-source-2");
});

it("copies exact reviewed source, candidate, and validation identities without storing a decision", async()=>{
  const user=userEvent.setup(); render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  await user.click(await screen.findByRole("button",{name:"Compare"}));
  const copy=await screen.findByRole("button",{name:"Copy comparison details"});
  expect(copy).toBeEnabled();
  copy.focus(); await user.keyboard("{Enter}");
  await waitFor(()=>expect(screen.getByText("Comparison details copied.")).toBeVisible());
  const payload=JSON.parse(await navigator.clipboard.readText());
  expect(payload).toEqual({
    contract:"ocd-cvw-reviewed-identity-v1",
    work_id:"city-of-god-book-1",
    source:{artifact_id:"city-source",version:"v1",sha256:"11".repeat(32),path:"raw/city/source.html"},
    candidate:{artifact_id:"city-tei",version:"v1",artifact_sha256:"22".repeat(32),path:"package/content.tei.xml",package_sha256:"aa".repeat(32)},
    validation:{status:"pass",report_sha256:"dd".repeat(32),source_manifest_sha256:"bb".repeat(32)},
  });
  expect(vi.mocked(fetch).mock.calls.every(([,init])=>!init||init.method===undefined||init.method==="GET")).toBe(true);
});

it("keeps the exact reviewed identity available when clipboard permission is denied", async()=>{
  const user=userEvent.setup();
  const writeText=vi.spyOn(navigator.clipboard,"writeText").mockRejectedValueOnce(new DOMException("denied","NotAllowedError"));
  render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  await user.click(await screen.findByRole("button",{name:"Compare"}));
  await user.click(await screen.findByRole("button",{name:"Copy comparison details"}));

  expect(writeText).toHaveBeenCalledOnce();
  expect(await screen.findByText("Could not use the clipboard. Select and copy the details below.")).toBeVisible();
  const fallback=screen.getByRole("textbox",{name:"Comparison details"});
  expect(fallback).toHaveValue(JSON.stringify({
    contract:"ocd-cvw-reviewed-identity-v1",
    work_id:"city-of-god-book-1",
    source:{artifact_id:"city-source",version:"v1",sha256:"11".repeat(32),path:"raw/city/source.html"},
    candidate:{artifact_id:"city-tei",version:"v1",artifact_sha256:"22".repeat(32),path:"package/content.tei.xml",package_sha256:"aa".repeat(32)},
    validation:{status:"pass",report_sha256:"dd".repeat(32),source_manifest_sha256:"bb".repeat(32)},
  },null,2));
  expect(vi.mocked(fetch).mock.calls.every(([,init])=>!init||init.method===undefined||init.method==="GET")).toBe(true);
});

it("disables identity copy when either compared artifact is not reopened exactly", async()=>{
  recordedState="drift";
  window.history.replaceState({},"","/review/works/city-of-god-book-1?mode=compare&leftStage=source&leftArtifact=city-source&leftVersion=v1&leftLocation=start&rightStage=tei&rightArtifact=city-tei&rightVersion=v1&rightLocation=start&linked=false&correspondence=source-to-tei-v1");
  render(<App/>);
  expect(await screen.findByRole("button",{name:"Copy comparison details"})).toBeDisabled();
  expect(screen.getByText("Includes file versions and validation report IDs.")).toBeVisible();
});

it("switches between retained source and TEI without inferred location correspondence", async()=>{
  const user=userEvent.setup(); render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  await user.click(await screen.findByRole("button",{name:"Reconstructed text"}));
  expect(await screen.findByText("The glorious city of God is my theme.")).toBeVisible();
  expect(screen.queryByText("Opened at the beginning. No matching passage is recorded for the other version.")).not.toBeInTheDocument();
  expect(window.location.search).toContain("fromStage=source");
});

it("opens an honest unlinked side-by-side comparison when correspondence is absent", async()=>{
  catalog.works[0].correspondence_sources=[];
  const user=userEvent.setup(); render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  await user.click(await screen.findByRole("button",{name:"Compare"}));
  expect(await screen.findByRole("heading",{name:"The City of God — Book I"})).toBeVisible();
  expect(screen.getByRole("region",{name:"Left pane: Source"})).toBeVisible();
  expect(screen.getByRole("region",{name:"Right pane: Reconstructed text"})).toBeVisible();
  expect(screen.getByRole("status",{name:"Correspondence status"})).toHaveTextContent("No passage matches recorded.");
  expect(screen.getByText("No passage matches recorded. Navigate each pane separately.")).toBeVisible();
  expect(screen.getByRole("checkbox")).toBeDisabled();
});

it("links navigation only from an explicit known mapping", async()=>{
  const user=userEvent.setup(); render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  await user.click(await screen.findByRole("button",{name:"Compare"}));
  const checkbox=await screen.findByRole("checkbox");
  expect(checkbox).toBeEnabled(); expect(checkbox).not.toBeChecked();
  await user.click(checkbox);
  expect(await screen.findByRole("checkbox")).toBeChecked();
  const left=screen.getByRole("region",{name:"Left pane: Source"});
  await user.selectOptions(within(left).getByRole("combobox",{name:"Left pane location"}),"chapter-1");
  await waitFor(()=>expect(window.location.search).toContain("rightLocation=chapter-1"));
  expect(screen.getByRole("status",{name:"Correspondence status"})).toHaveTextContent("Mapping: source-to-tei-v1");
});

it("fails closed on removed Structure routes before calling a Structure API", async()=>{
  window.history.replaceState({},"","/review/works/city-of-god-book-1?mode=structure");
  render(<App/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("This viewer supports only Read and Compare");
  expect(vi.mocked(fetch).mock.calls.some(([input])=>String(input).includes("/structure"))).toBe(false);
});

it("rejects a removed artifact identity without offering comparison", async()=>{
  recordedState="drift";
  window.history.replaceState({},"","/review/works/city-of-god-book-1?stage=source&artifact=old-source&version=old-v1&location=start");
  render(<App/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("The requested source artifact identity was not returned");
  expect(screen.queryByRole("button",{name:"The City of God — Book I"})).not.toBeInTheDocument();
});

it("renders image facsimiles only from governed same-origin pane identity", async()=>{
  sourcePresentation={declared_kind:"image-facsimile",kind:"image-facsimile",render_target:"in-browser",document:{nodes:[{type:"image",text:"Retained page facsimile"}]}};
  const user=userEvent.setup(); render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  const image=await screen.findByRole("img",{name:"Retained page facsimile"});
  expect(image).toHaveAttribute("src","/api/review/v1/works/city-of-god-book-1/stages/source/bytes?expected_artifact=city-source&expected_version=v1&expected_sha256="+"11".repeat(32));
  expect(image).toHaveAttribute("loading","lazy");
});

it("selects preview then original through existing agent disclosure and resets on navigation",async()=>{
  sourcePresentation={declared_kind:"image-facsimile",kind:"image-facsimile",render_target:"in-browser",
    document:{nodes:[{type:"image",text:"Retained page facsimile"}]},
    native_image:{normalized_dimensions:{width:2400,height:1800},preview:{variant:"preview",width:1280,height:960,media_type:"image/png",transform_version:"cvw-native-preview-v1"}}};
  const original=vi.mocked(fetch).getMockImplementation()!;
  const imagePaths:string[]=[];
  vi.stubGlobal("URL",class extends URL {static createObjectURL=()=>"blob:selected-image";static revokeObjectURL=()=>{};});
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const url=new URL(String(input),"http://localhost");
    if(url.pathname.endsWith("/image")||url.pathname.endsWith("/bytes")){
      imagePaths.push(String(input));
      const metadata={variant:"preview",source:{id:"city-source",version:"v1",sha256:"11".repeat(32),work:"city-of-god-book-1",stage:"source"},output:{width:1280,height:960,bytes:4,sha256:"55".repeat(32)}};
      return {ok:true,status:200,headers:new Headers(url.pathname.endsWith("/image")?{"X-CVW-Image-Metadata":JSON.stringify(metadata)}:{}),blob:async()=>new Blob(["test"])} as Response;
    }
    return original(input,init);
  });
  window.history.replaceState({},"",`${comparePath}&focus=agent`);
  const user=userEvent.setup(); render(<App/>);
  await screen.findByRole("img",{name:"Retained page facsimile"});
  expect(imagePaths).toHaveLength(1);
  expect(imagePaths[0]).toContain("/image?");
  await user.click(screen.getByText("Compare controls",{selector:"summary"}));
  await user.selectOptions(screen.getByRole("combobox",{name:"Left image resolution"}),"original");
  await waitFor(()=>expect(imagePaths).toHaveLength(2));
  expect(imagePaths[1]).toContain("/bytes?");
  expect(imagePaths[1]).toContain(`expected_sha256=${"11".repeat(32)}`);
  await user.selectOptions(screen.getByRole("combobox",{name:"Left pane location"}),"chapter-1");
  await waitFor(()=>expect(imagePaths).toHaveLength(3));
  expect(imagePaths[2]).toContain("/image?");
  expect(document.querySelector(".native-image")).toHaveAttribute("data-image-variant","preview");
});

it("keeps PDF typed nodes readable and degrades unknown renderers honestly",()=>{
  const {unmount}=render(<>{renderPresentation({declared_kind:"pdf-native",kind:"pdf-native",render_target:"in-browser",document:{nodes:[{type:"paragraph",text:"PDF text stays readable."}]}})}</>);
  expect(screen.getByText("PDF text stays readable.")).toBeVisible(); unmount();
  render(<>{renderPresentation({declared_kind:"pdf-native",kind:"future-renderer",render_target:"in-browser",document:{nodes:[{type:"paragraph",text:"Typed fallback stays readable."}]}})}</>);
  expect(screen.getByRole("status")).toHaveTextContent("This file is shown in a basic text view.");
  expect(screen.getByText("Typed fallback stays readable.")).toBeVisible();
});

it("rejects duplicate governed route identities before artifact dispatch", async()=>{
  window.history.replaceState({},"","/review/works/city-of-god-book-1?stage=source&artifact=one&artifact=two&version=v1&location=start");
  render(<App/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("artifact must appear exactly once");
  expect(vi.mocked(fetch).mock.calls.some(([input])=>String(input).includes("/stages/"))).toBe(false);
});

it("does not display a response whose recorded identity differs from the requested route", async()=>{
  const current=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input:RequestInfo|URL)=>{
    const response=await current(input);
    if(String(input).includes("/stages/source")){
      const body=await response.json() as StageView;
      return jsonResponse({...body,recorded_context:{...body.recorded_context,requested:{artifact_id:"different",version:"v1",location:"start"}}});
    }
    return response;
  });
  window.history.replaceState({},"","/review/works/city-of-god-book-1?stage=source&artifact=city-source&version=v1&location=start");
  render(<App/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("stage response did not match the requested review context");
});

it("never dispatches Notes requests from Library, Read, or Compare", async()=>{
  const user=userEvent.setup(); render(<App/>);
  await user.click(await screen.findByRole("button",{name:"Open The City of God — Book I"}));
  await user.click(await screen.findByRole("button",{name:"Compare"}));
  await screen.findByRole("heading",{name:"The City of God — Book I"});
  expect(vi.mocked(fetch).mock.calls.some(([input])=>String(input).includes("/notes"))).toBe(false);
  fireEvent.popState(window);
});

function nativeImageFixture() {
  sourcePresentation={declared_kind:"image-facsimile",kind:"image-facsimile",render_target:"in-browser",document:{nodes:[{type:"image",text:"Known page"}]},native_image:{original_dimensions:{width:2400,height:1800},normalized_dimensions:{width:2400,height:1800},preview:{variant:"preview",width:1280,height:960,media_type:"image/png",transform_version:"cvw-native-preview-v1"}}};
  vi.stubGlobal("URL",class extends URL {static createObjectURL=vi.fn(()=>"blob:known-image");static revokeObjectURL=vi.fn();});
  const current=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(...args)=>{
    const url=new URL(String(args[0]),"http://localhost");
    if(!url.pathname.endsWith("/image")&&!url.pathname.endsWith("/bytes"))return current(...args);
    const region=url.searchParams.get("region")?.split(",").map(Number);
    const metadata=url.pathname.endsWith("/image")?{variant:region?"region":"preview",region,source:{id:"city-source",version:"v1",sha256:"11".repeat(32),work:"city-of-god-book-1",stage:"source"},output:{width:region?.[2]??1280,height:region?.[3]??960,bytes:4,sha256:"33".repeat(32)},transform:{version:region?"cvw-native-region-v1":"cvw-native-preview-v1"}}:null;
    return {ok:true,status:200,headers:new Headers(metadata?{"X-CVW-Image-Metadata":JSON.stringify(metadata)}:{}),blob:async()=>new Blob(["test"])} as Response;
  });
}

it("reopens independent image regions through history and returns one pane to original",async()=>{
  nativeImageFixture();
  const dual=comparePath.replace("rightStage=tei","rightStage=source").replace("rightArtifact=city-tei","rightArtifact=city-source").replace("correspondence=source-to-tei-v1","correspondence=absent");
  const regionRoute=`${dual}&focus=agent&leftRegion=50,825,1250,480&leftImageSha256=${"11".repeat(32)}&rightRegion=50,1305,1250,400&rightImageSha256=${"11".repeat(32)}`;
  window.history.replaceState({},"",regionRoute);
  const user=userEvent.setup();const mounted=render(<App/>);
  await waitFor(()=>expect(document.querySelectorAll(".native-image img")).toHaveLength(2));
  expect(document.querySelector('[data-review-side="left"] .native-image')).toHaveAttribute("data-image-region","50,825,1250,480");
  expect(document.querySelector('[data-review-side="right"] .native-image')).toHaveAttribute("data-image-region","50,1305,1250,400");
  expect(vi.mocked(fetch).mock.calls.filter(([url])=>String(url).includes("/image?")).every(([url])=>String(url).includes("variant=region"))).toBe(true);
  await user.click(screen.getByText("Compare controls",{selector:"summary"}));
  await user.selectOptions(screen.getByRole("combobox",{name:"Left image resolution"}),"original");
  await waitFor(()=>expect(document.querySelector('[data-review-side="left"] .native-image')).toHaveAttribute("data-image-variant","original"));
  expect(new URLSearchParams(window.location.search).get("leftRegion")).toBeNull();
  expect(new URLSearchParams(window.location.search).get("rightRegion")).toBe("50,1305,1250,400");
  window.history.back();
  await waitFor(()=>expect(document.querySelector('[data-review-side="left"] .native-image')).toHaveAttribute("data-image-region","50,825,1250,480"));
  window.history.forward();
  await waitFor(()=>expect(document.querySelector('[data-review-side="left"] .native-image')).toHaveAttribute("data-image-variant","original"));
  mounted.unmount();render(<App/>);
  await waitFor(()=>expect(document.querySelector('[data-review-side="right"] .native-image')).toHaveAttribute("data-image-region","50,1305,1250,400"));
  await user.click(screen.getByText("Compare controls",{selector:"summary"}));
  await user.click(screen.getByRole("button",{name:"Exit focus view"}));
  expect(screen.getByRole("combobox",{name:"Right image resolution"})).toHaveValue("region");
  await user.selectOptions(screen.getByRole("combobox",{name:"Right image resolution"}),"original");
  await waitFor(()=>expect(document.querySelector('[data-review-side="right"] .native-image')).toHaveAttribute("data-image-variant","original"));
});

it("copies the selected image region scope and clears it only when that pane changes",async()=>{
  nativeImageFixture();
  const regionRoute=`${comparePath}&focus=agent&leftRegion=1,2,30,20&leftImageSha256=${"11".repeat(32)}`;
  window.history.replaceState({},"",regionRoute);
  const user=userEvent.setup();render(<App/>);
  await screen.findByRole("img");
  await user.click(screen.getByText("Compare controls",{selector:"summary"}));
  await user.click(screen.getByRole("button",{name:"Copy comparison details"}));
  const payload=JSON.parse(await navigator.clipboard.readText());
  expect(payload.image_view_scope.left.selection).toEqual({variant:"region",region:"1,2,30,20",source_sha256:"11".repeat(32)});
  expect(new URL(payload.image_view_scope.route,"http://localhost").searchParams.get("leftRegion")).toBe("1,2,30,20");
  expect(payload.image_view_scope.meaning).toContain("not asserted");
  await user.selectOptions(screen.getByRole("combobox",{name:"Right pane location"}),"chapter-1");
  await waitFor(()=>expect(screen.getByRole("main")).toHaveAttribute("data-review-state","ready"));
  expect(new URLSearchParams(window.location.search).get("leftRegion")).toBe("1,2,30,20");
  await user.click(screen.getByText("Compare controls",{selector:"summary"}));
  await user.selectOptions(screen.getByRole("combobox",{name:"Left pane"}),"tei");
  await waitFor(()=>expect(screen.getByRole("main")).toHaveAttribute("data-review-state","ready"));
  expect(new URLSearchParams(window.location.search).get("leftRegion")).toBeNull();
  expect(new URLSearchParams(window.location.search).get("leftImageSha256")).toBeNull();
});

it.each(["leftRegion=0,0,1,1",`leftRegion=01,0,1,1&leftImageSha256=${"11".repeat(32)}`,`leftRegion=0,0,1,1&leftImageSha256=${"11".repeat(32)}&leftImage=original`,`leftRegion=0,0,1,1&leftImageSha256=${"11".repeat(32)}&leftRegion=0,0,2,2`])("rejects ambiguous region URL before requesting Compare: %s",async(query)=>{
  window.history.replaceState({},"",`${comparePath}&${query}`);render(<App/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid review route");
  expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes("/compare"))).toBe(false);
});
