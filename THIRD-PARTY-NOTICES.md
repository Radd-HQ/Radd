# Third-party notices

Radd is licensed under AGPL-3.0-only (see [LICENSE](LICENSE)); the extension
SDKs — `sdk/` (Python) and `web/packages/plugin-sdk/` (frontend) — are
Apache-2.0, so plugins and external integrations can be licensed however their
authors choose.

All runtime dependencies are under permissive or weak-copyleft licenses
(MIT/BSD/ISC/Apache-2.0/PSF, plus LGPL-3.0 for `psycopg` and `ldap3` and
MPL-2.0 for a handful of files-level-copyleft packages) — used as unmodified
libraries, compatible with this project's licensing. Their license texts ship
inside the respective packages. The notices below cover third-party material
**copied into this repository** rather than merely depended on.

## Milkdown (MIT)

`web/src/components/editor/diff/decoration-plugin.ts`, `doc-utils.ts` and
`merge-changes.ts` are forks/ports of Milkdown's diff components
(`@milkdown/components/src/diff/*`), modified for per-block review.

> The MIT License (MIT)
>
> Copyright (c) 2020-present Mirone
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
> THE SOFTWARE.

## Inter (SIL Open Font License 1.1)

`web/public/fonts/inter-*.woff2` — Copyright (c) 2016 The Inter Project
Authors (<https://github.com/rsms/inter>). Licensed under the SIL Open Font
License 1.1; the full text ships beside the font files as
[web/public/fonts/OFL.txt](web/public/fonts/OFL.txt).
