# Vendored browser files

Served by `nov serve`; nothing is fetched from a CDN at run time.

| File | Package | Licence | Source | SHA-256 |
|---|---|---|---|---|
| `htmx.min.js` | htmx.org 2.0.11 | 0BSD | https://unpkg.com/htmx.org@2.0.11/dist/htmx.min.js | `d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717` |
| `sse.js` | htmx-ext-sse 2.2.4 | 0BSD | https://unpkg.com/htmx-ext-sse@2.2.4/sse.js | `3b5992a541619babefc4c169505af474df5c3039da51e59b96ccf9241ecd61d2` |
| `fonts/Geist-Variable.woff2` | Geist 1.8.1, `Geist/webfonts/Geist[wght].woff2` | OFL-1.1 (`fonts/OFL.txt`) | https://github.com/vercel/geist-font/releases/download/v1.8.1/geist-font-v1.8.1.zip | `9ce2d97863cab59a0c7522534112d6c42a4e25c0e6b2ab37766761b0f82cfbd6` |
| `fonts/GeistMono-Variable.woff2` | Geist 1.8.1, `GeistMono/webfonts/GeistMono[wght].woff2` | OFL-1.1 (`fonts/OFL.txt`) | as above | `119f3e159fc15dd77311e929d3a657a193b57a3e625234666bc43c6e2b1127f7` |
| `fonts/OFL.txt` | Geist 1.8.1, `OFL.txt` | | as above | `c683bfbcc7e087f5d37a54ef628f10387c451a83ddc459b151403a164ac46c90` |
| `lucide.svg` | lucide-static 1.61.0, 30 icons | ISC (`LICENSE-lucide.txt`) | https://registry.npmjs.org/lucide-static/-/lucide-static-1.61.0.tgz | `94226a84ac4fde64a94f07ab47275f003df309caa2713927a3b34f4ffdedd0ba` |
| `LICENSE-lucide.txt` | lucide-static 1.61.0, `LICENSE` | | as above | `b495047bd93a9b06913511076f504daba17d5bbeb3e0650f3bb53a4220329c57` |

The release zip's SHA-256 is `70f42c1452fb6df12ea183e20a65999157354f91d11dac18b4c713e383808ec2`; the lucide-static tarball's is `62773cd2ee411ad2e37c1973d1e4c4b49f9a6c57da6b5d5d0abca08756ba75f1`.

htmx stays on the 2.x line (plan §6.3); 4.x is a new major version.

## The icon sprite

`lucide.svg` holds one `<symbol>` per icon the templates use, built by `tools/make_lucide_sprite.py` (its `ICONS` lists them):

1. Download the tarball above and check its SHA-256.
2. Extract it to an empty folder: `tar xzf lucide-static-1.61.0.tgz`.
3. `uv run python tools/make_lucide_sprite.py <folder>/package/icons`.

To add an icon, add its name to `ICONS` and run step 3 again; the test that reads the templates fails while a used icon has no symbol. The source SVGs' SHA-256:

| Icon | SHA-256 |
|---|---|
| activity | `ad2e728ce1a3bf4dee93223ce3912c7b52cd2ee061c832e08ba0a14b028f68ee` |
| arrow-down | `e4aef5810b8e5e1304c735f2af5c6f7c4cdebad1e00b4b2ebbf2e1bdfea17528` |
| arrow-up | `f76f6cc5e50fe25865dbf403a816016b1cf8d4de1bb4e230ff5b541b69bcde34` |
| book-open | `369a07ee7ab13c9cc464f70aada0c28462a4778dcbd6676044f3d3753d7dc6b6` |
| check | `cf5d8f45a017604917c0d74ed9c49c6926b0df780c4c9ad3ad85fb7a392bf746` |
| chevron-down | `763bbc7f305bad8b852b5ae5feadfc08858acf97f19a5897aa8f1fe636abed45` |
| chevron-right | `2af3089fa09497d5725172b172196d193cbe8205bf70ad6f9078ce4773285001` |
| circle-alert | `9297d24761982135593d8a24fa90f3b901e36ec3b79a744df61012b4bb74addc` |
| circle-check | `3691ff0253b550e0e2a558064f50a788d8b4d0664302548d5dd33321d368fb5b` |
| clock | `2a50ff1030ae5591447dd5b278bdbd24e7dda3c24e2133348e7a66231fd6e787` |
| external-link | `20ae73316402f4629ac1c69576014e2f3956f3ca6e14effeab868d4b5a8cc2ef` |
| file-text | `0f68908abe19543be363a403a4239f288236840ede01eec2af65830c3ba7f22c` |
| git-compare | `02934aa7b03333df442e65882a59402180a3817be3d23c227b9b5ddbce12eb6d` |
| globe | `994924c198fe332f0de7eb5953610c6bce145b93db86c97d7183ce170a6038cc` |
| hammer | `01a9c60be5b0ff4894baea9d7d6b0cf706a9e5f9252dd0a23e57fd91a743c04d` |
| languages | `204ea2ef94b9fdbf41d795340b930e1e149180c007fb030316092a74be310b4c` |
| layers | `13f4094d328912b62ac21df6d423295178ab92d7120f975e9875c7078b13a132` |
| library | `501eae9a3d73b69c0b3ddfe196fc482836915ec77060afa51f73b88cf50fae7f` |
| list | `8c57a520002147ace4c2e3127def471f29af0abb7113acdccb1284e4286ebaae` |
| loader | `dbb1e46eaabc4449268776ba8f6bbea6ccda8c0ae75a3af6858d3962d31e286d` |
| panel-left | `7e3e798c9423b2ed2727768b5494a8d349331d4866f04048041acd1aec2c220b` |
| pin | `a3857df963b2a34a7bfd83feab7c60d10fb6401b07eee757fe2140d789626f32` |
| pin-off | `445d6a4ff73ef3fdfa70a0f38a5be2bbfd41198317e23a7dd6fc5d8fa66f6696` |
| plus | `dfcf07b39b0f4c0b422595ae488fb08c468ef4782f6ef37d0deceaadfb2a5693` |
| refresh-cw | `801cc03b84a654de114a2707c9b1c6aa9a3b732c4ffc9e5df0f63f02e1ba0105` |
| rotate-ccw | `3c85ba84f7aba5a0b8fd9fe58b0e61c64787777e71ab41fdd4c4a6dcac3250b5` |
| search | `e0d89f53155655032f5c07fd8da930800b62b69a778d1dd76b388b9b78bf1d3f` |
| square | `3855d336619de5adc61a0b5293db82cb9f5456b859a7daf0cd249653c6f31063` |
| triangle-alert | `563e5e851a38ddc378dc98e80ae650ee28180846c7ce14ba51d40bc2107c9362` |
| x | `a611112e8946480120e5e96f1d849651df76fa502f6190e293defaf6c4f56b07` |
