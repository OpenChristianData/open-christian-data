<?xml version="1.0" encoding="UTF-8"?>
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron">
  <sch:ns prefix="tei" uri="http://www.tei-c.org/ns/1.0"/>
  <sch:pattern id="witnessless-lemma-responsibility">
    <sch:rule context="tei:lem[not(@wit)]">
      <sch:assert test="@resp">witnessless lem must carry @resp.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern id="word-facs-zone-resolution">
    <sch:rule context="tei:w[@facs]">
      <sch:assert test="count(//tei:zone[concat('#', @xml:id) = current()/@facs]) = 1">dangling facs <sch:value-of select="@facs"/> must match exactly one zone.</sch:assert>
    </sch:rule>
  </sch:pattern>
</sch:schema>
