# Licensing

Date: 2026-10-25

## Decision

BPSync uses the unchanged PolyForm Strict License 1.0.0, with a copyright line
for BPSync contributors above the license text. The license permits personal
and other noncommercial use, including use by the noncommercial organizations
it lists, and does not permit modifying, distributing, or making new works
based on the software. Commercial use requires a separate paid agreement.
Emrah Diril is the licensing contact at emrah@diril.org.

## Rationale

The intended model is free personal use, paid business use, and source that
people can read but not fork, redistribute, or build on. PolyForm Strict is
the established license for exactly that combination, so BPSync needs no
custom terms. PolyForm Noncommercial, which HLSync uses, was considered and
rejected because it allows noncommercial modification and redistribution.

## Boundaries

The source is available but not open source. Users cannot change BPSync even
for their own use; bug fixes come from the project. Strict has no
distribution grant, so it has no required-notice mechanism.

SPDX has no identifier for PolyForm Strict, so package metadata uses
`LicenseRef-PolyForm-Strict-1.0.0`.

Public hosting on GitHub lets anyone view and fork the repository within
GitHub under GitHub's terms; the license still governs any use outside them.

Runtime dependencies must use permissive licenses (such as MIT, BSD, or
Apache) that allow BPSync to be distributed under these terms. Copyleft code
such as WordPress's GPL source cannot be incorporated; BPSync reimplements any
WordPress behavior it needs and checks it against WordPress's output.

Pricing, commercial-license duration, and support commitments belong in the
separate commercial agreement. There is no runtime license enforcement.
