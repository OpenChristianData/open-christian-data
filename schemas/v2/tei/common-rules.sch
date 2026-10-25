<?xml version='1.0' encoding='UTF-8'?>
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron">
  <sch:title>OCD provisional TEI common profile</sch:title>
  <sch:ns prefix="tei" uri="http://www.tei-c.org/ns/1.0" />
  <sch:ns prefix="xml" uri="http://www.w3.org/XML/1998/namespace" />
  <sch:pattern id="ocd-registry-generated-closed-values">
    <sch:rule context="tei:div[@type]">
      <sch:assert id="ocd-controlled-div-type" test="@type = 'work' or @type = 'part' or @type = 'book' or @type = 'chapter' or @type = 'section' or @type = 'subsection' or @type = 'sermon' or @type = 'service' or @type = 'collect' or @type = 'letter' or @type = 'preface' or @type = 'foreword' or @type = 'introduction' or @type = 'prologue' or @type = 'dedication' or @type = 'notes' or @type = 'title-page' or @type = 'half-title-page' or @type = 'copyright-page' or @type = 'imprint' or @type = 'colophon' or @type = 'dictionary-entry'">[ocd-controlled-div-type] A division type must be admitted by the controlled-values registry.</sch:assert>
    </sch:rule>
    <sch:rule context="tei:note[@place]">
      <sch:assert id="ocd-controlled-note-place" test="@place = 'foot' or @place = 'end'">[ocd-controlled-note-place] A note place must be admitted by the controlled-values registry.</sch:assert>
    </sch:rule>
    <sch:rule context="tei:ref[@type]">
      <sch:assert id="ocd-controlled-ref-type" test="@type = 'note' or @type = 'scripture'">[ocd-controlled-ref-type] A reference type must be admitted by the controlled-values registry.</sch:assert>
    </sch:rule>
    <sch:rule context="tei:list[@type]">
      <sch:assert id="ocd-controlled-list-type" test="@type = 'ordered' or @type = 'bulleted'">[ocd-controlled-list-type] A list type must be admitted by the controlled-values registry.</sch:assert>
    </sch:rule>
    <sch:rule context="tei:hi[@rend]">
      <sch:assert id="ocd-controlled-hi-rend" test="@rend = 'italic' or @rend = 'bold' or @rend = 'superscript' or @rend = 'subscript' or @rend = 'small-caps'">[ocd-controlled-hi-rend] A highlight rendition must be admitted by the controlled-values registry.</sch:assert>
    </sch:rule>
    <sch:rule context="tei:idno[@type]">
      <sch:assert id="ocd-controlled-idno-type" test="@type = 'ocd-work-id' or @type = 'ocd-textual-form-id' or @type = 'ocd-edition-id' or @type = 'ocd-acquisition-id' or @type = 'sha256' or @type = 'git-commit-sha1'">[ocd-controlled-idno-type] A identifier type must be admitted by the controlled-values registry.</sch:assert>
    </sch:rule>
    <sch:rule context="tei:head[@type]">
      <sch:assert id="ocd-controlled-head-type" test="@type = 'headword'">[ocd-controlled-head-type] A heading type must be admitted by the controlled-values registry.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="ocd-note-target-resolution">
    <sch:rule context="tei:ref[@type='note']">
      <sch:assert id="ocd-note-target-required" test="starts-with(normalize-space(@target), '#') and string-length(substring-after(normalize-space(@target), '#')) &gt; 0">[ocd-note-target-required] A note reference must use a nonempty fragment target.</sch:assert>
      <sch:assert id="ocd-note-target-resolves" test="count(//tei:note[@xml:id = substring-after(normalize-space(current()/@target), '#')]) = 1">[ocd-note-target-resolves] A note reference must resolve to exactly one note.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="ocd-reference-locator-semantics">
    <sch:rule context="tei:ref[@target or @cRef]">
      <sch:assert id="ocd-ref-target-cRef-exclusive" test="not(@target and @cRef)">[ocd-ref-target-cRef-exclusive] A reference cannot carry both target and cRef.</sch:assert>
      <sch:assert id="ocd-ref-target-uri" test="not(@target) or (normalize-space(@target) = string(@target) and normalize-space(@target) != '' and not(contains(@target, ' ')))">[ocd-ref-target-uri] A target locator must be a nonempty space-free URI or fragment.</sch:assert>
      <sch:assert id="ocd-ref-cRef-scripture" test="not(@cRef) or (@type = 'scripture' and normalize-space(@cRef) = string(@cRef) and normalize-space(@cRef) != '' and not(@target))">[ocd-ref-cRef-scripture] A canonical cRef requires type scripture and cannot share target.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="ocd-identifier-context-and-format">
    <sch:rule context="tei:idno[@type='sha256' or @type='git-commit-sha1']">
      <sch:assert id="ocd-sha256-format" test="not(@type = 'sha256') or (string-length(string(.)) = 64 and translate(string(.), '0123456789abcdef', '') = '')">[ocd-sha256-format] sha256 must be exactly 64 lowercase hexadecimal characters.</sch:assert>
      <sch:assert id="ocd-git-commit-sha1-format" test="not(@type = 'git-commit-sha1') or (string-length(string(.)) = 40 and translate(string(.), '0123456789abcdef', '') = '')">[ocd-git-commit-sha1-format] git-commit-sha1 must be exactly 40 lowercase hexadecimal characters.</sch:assert>
      <sch:assert id="ocd-source-idno-context" test="ancestor::tei:sourceDesc">[ocd-source-idno-context] Source digest and revision identifiers belong under a source description.</sch:assert>
    </sch:rule>
    <sch:rule context="tei:idno[starts-with(@type, 'ocd-') and substring(@type, string-length(@type) - 2) = '-id']">
      <sch:assert id="ocd-identity-idno-context" test="ancestor::tei:teiHeader and not(ancestor::tei:text)">[ocd-identity-idno-context] OCD identity identifiers belong in the TEI header, outside the text.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="ocd-undeclared-quote-type-pattern">
    <sch:rule context="tei:quote[@type]">
      <sch:assert id="ocd-undeclared-quote-type" test="false()">[ocd-undeclared-quote-type] quote type is not admitted by the common profile; select a complete bound extension.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="ocd-undeclared-ab-type-pattern">
    <sch:rule context="tei:ab[@type]">
      <sch:assert id="ocd-undeclared-ab-type" test="false()">[ocd-undeclared-ab-type] ab type is not admitted by the common profile; select a complete bound extension.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="ocd-undeclared-p-rend-pattern">
    <sch:rule context="tei:p[@rend]">
      <sch:assert id="ocd-undeclared-p-rend" test="false()">[ocd-undeclared-p-rend] paragraph rendition is not admitted by the common profile; select a complete bound extension.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="ocd-undeclared-note-type-pattern">
    <sch:rule context="tei:note[@type]">
      <sch:assert id="ocd-undeclared-note-type" test="false()">[ocd-undeclared-note-type] note type is not admitted by the common profile; select a complete bound extension.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="ocd-undeclared-annotation-pattern">
    <sch:rule context="tei:*[@ana]">
      <sch:assert id="ocd-undeclared-annotation" test="false()">[ocd-undeclared-annotation] annotation is not admitted by the common profile; select a complete bound extension.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="ocd-undeclared-subtype-pattern">
    <sch:rule context="tei:*[@subtype]">
      <sch:assert id="ocd-undeclared-subtype" test="false()">[ocd-undeclared-subtype] element subtype is not admitted by the common profile; select a complete bound extension.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="ocd-undeclared-style-pattern">
    <sch:rule context="tei:*[@style]">
      <sch:assert id="ocd-undeclared-style" test="false()">[ocd-undeclared-style] style declaration is not admitted by the common profile; select a complete bound extension.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="ocd-undeclared-rendition-pattern">
    <sch:rule context="tei:*[@rendition]">
      <sch:assert id="ocd-undeclared-rendition" test="false()">[ocd-undeclared-rendition] rendition pointer is not admitted by the common profile; select a complete bound extension.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="ocd-other-custom-types">
    <sch:rule context="tei:*[@type][not(self::tei:div or self::tei:ref or self::tei:list or self::tei:idno or self::tei:head or self::tei:quote or self::tei:ab or self::tei:note)]">
      <sch:assert id="ocd-undeclared-element-type" test="false()">[ocd-undeclared-element-type] This element type requires an explicit source-bound extension.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="ocd-dictionary-entry-structure">
    <sch:rule context="tei:div[@type='dictionary-entry']">
      <sch:assert id="ocd-dictionary-entry-headword" test="count(.//tei:head[@type='headword'][normalize-space(.) != ''][count(ancestor::tei:div[@type='dictionary-entry'][1] | current()) = 1]) &gt; 0">[ocd-dictionary-entry-headword] A dictionary entry must contain its own nonempty headword heading; nested entry headings do not satisfy the outer entry.</sch:assert>
    </sch:rule>
  </sch:pattern>
</sch:schema>