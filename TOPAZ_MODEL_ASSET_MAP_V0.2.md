# Topaz Gigapixel 模型资产地图 V0.2

生成日期：2026-08-20  
扫描目录：`D:\Adobe\Topaz Gigapixel\models`、`D:\Adobe\Topaz Gigapixel\logs`

## 1. 严格只读策略

- 内容读取白名单：`.json`、`.tzlog`、`.log`。
- `models` 下其他文件只通过 `Get-FileHash -Algorithm SHA256` 做授权的哈希流读取；不输出、不解析、不加载内容。
- `logs` 下两个 `.txt` 仅记录文件名、大小、修改时间，SHA256 标记为 `NOT_COMPUTED_NOT_AUTHORIZED`。
- 未执行 Topaz、模型推理或权重解析；未修改 Topaz 与 HDDE 既有文件。

## 2. 文件统计

| 范围 | 文件数量 | 总字节 | GiB |
|---|---:|---:|---:|
| models | 157 | 24576503889 | 22.888653 |
| logs | 7 | 6959464 | 0.006482 |
| 合计 | 164 | 24583463353 | 22.895134 |

- JSON 数量：60
- TZ2 数量：87
- 其他文件数量：17

### 2.1 扩展名统计

| 扩展名 | 数量 | 字节 |
|---|---:|---:|
| .bin | 2 | 788480 |
| .data | 3 | 6179651584 |
| .json | 60 | 147393 |
| .log | 1 | 83 |
| .pb | 2 | 4880199168 |
| .txt | 4 | 8503087 |
| .tz2 | 87 | 13512385759 |
| .tzlog | 4 | 40875 |
| .yaml | 1 | 1746924 |

## 3. 模型族分类

分类只使用用户指定族名与文件名前缀；未命中者一律 `UNKNOWN`。日志文件不进入模型族统计。

| 模型族 | 文件 | JSON | TZ2 | 字节 |
|---|---:|---:|---:|---:|
| Wonder | 4 | 4 | 0 | 5938 |
| GMP | 8 | 2 | 6 | 619827903 |
| TRF | 5 | 2 | 3 | 104062947 |
| GFP | 6 | 3 | 3 | 222996184 |
| IRWN | 9 | 3 | 3 | 6190532773 |
| GCLC | 10 | 0 | 10 | 293681 |
| LDCLC | 3 | 0 | 3 | 191012 |
| SSD | 12 | 7 | 5 | 2099876017 |
| UNKNOWN | 100 | 39 | 54 | 15338717434 |

`MODEL_FAMILY_COUNT=9`（含 `UNKNOWN`；8 个指定命名族均有文件证据）。

## 4. 完整文件资产清单

SHA256 为大写十六进制；`NOT_COMPUTED_NOT_AUTHORIZED` 表示该日志 `.txt` 不在内容读取白名单，也不属于模型权重哈希授权范围。

| 根 | 相对路径 | 类型 | 模型族 | 字节 | SHA256 | 修改时间 UTC |
|---|---|---|---|---:|---|---|
| models | ap_all.json | .json | UNKNOWN | 1636 | 6F9D7D2D3EF7DC17130743BFEE84B1C027C07C965B81A703047891694F79941B | 2026-08-12T12:33:14.0000000Z |
| models | apnb-v2-fp16-512x512-rev2-ox.tz2 | .tz2 | UNKNOWN | 3481839 | 2248D9BFA72058CEB9A9CDE5A010C339874438077D81AEC57568F5A8C37E71CF | 2026-08-19T04:48:34.9795469Z |
| models | claa-v1-fp32-512x512-ov.tz2 | .tz2 | UNKNOWN | 4818242 | 48DB672E45FA1589CD7D246FC42D9137523E85DFF8ECACF3658C637E88104D80 | 2026-08-19T04:48:37.6789379Z |
| models | claa.json | .json | UNKNOWN | 1300 | 889C1169E28568E2BA4A4861A8040A9C3ED9A33185CF552BB79845A100FC13BC | 2026-08-12T12:33:16.0000000Z |
| models | clc-v2-fp32-512x512-ov.tz2 | .tz2 | UNKNOWN | 29574 | 01F06E8D6437EC7149A0110DE758C1C21EA55FFDD391779656430F7D8396B8B4 | 2026-08-19T04:48:38.4233318Z |
| models | default_prompt.bin | .bin | UNKNOWN | 315392 | EE1A75A2EEA00EFB073D52DF5A4B119AE795BFFB5A8C422A4B8BE153AA609CB1 | 2026-08-19T04:48:39.2066171Z |
| models | gclc-v1-fp16-128x128-2x-ov.tz2 | .tz2 | GCLC | 29281 | 3CF7FAEFC6D1A51350C2CA2D7B6B22ADFB9707E74D4898C5D74405BBB0F0411C | 2026-08-19T04:48:40.0125175Z |
| models | gclc-v1-fp16-128x128-4x-ov.tz2 | .tz2 | GCLC | 29281 | 7B0F9B70CB9FB9AD95EC38785F6D1CAA4C56E77745E59DA664A64E2485A9383F | 2026-08-19T04:48:40.8237896Z |
| models | gclc-v1-fp16-192x192-1x-ov.tz2 | .tz2 | GCLC | 29277 | F5B7496FC35BE8A0CF55283AD0772C44DDAF98B60B1BAEB7D00EAF1D4F956474 | 2026-08-19T04:48:41.6082527Z |
| models | gclc-v1-fp16-192x192-2x-ov.tz2 | .tz2 | GCLC | 29281 | 8A148451739545CCFB1DC15B2FBDF18AFE4E9BB54D83C440A14DD340128B4BE3 | 2026-08-19T04:48:42.4559443Z |
| models | gclc-v1-fp16-192x192-4x-ov.tz2 | .tz2 | GCLC | 29281 | 62CE8DA1CE6791D6328D9611061829ABEB367EE0D8D36199FD7E7D935D4BDB2F | 2026-08-19T04:48:43.2068034Z |
| models | gclc-v1-fp16-96x96-2x-ov.tz2 | .tz2 | GCLC | 29269 | 471FAE5C6D53662C3A2A95C1DDCBDD7E304E5002DAA9E30508013C41E9FD861E | 2026-08-19T04:48:43.9899300Z |
| models | gclc-v1-fp16-96x96-4x-ov.tz2 | .tz2 | GCLC | 29269 | 6EAB9911A3FA3F16B5F089238CA72B706F67F3C53399091F3AFF7E4C82B0142F | 2026-08-19T04:48:44.7735421Z |
| models | gclc-v1-fp32-192x192-1x-ov.tz2 | .tz2 | GCLC | 29578 | 877AE5EB3E1624F90F96CEF8A3FECC094C4D7DD3B07A63F25BF4EDF745D7E86A | 2026-08-19T04:48:45.5572441Z |
| models | gclc-v1-fp32-192x192-2x-ov.tz2 | .tz2 | GCLC | 29582 | 5275BF0FF9DD2C5A0F73CA84300AF4F96AE4D86F2BAD07A5FA78A91DED601C8B | 2026-08-19T04:48:46.3401220Z |
| models | gclc-v1-fp32-192x192-4x-ov.tz2 | .tz2 | GCLC | 29582 | 839241F705134E8F51B91571BEBF428AEAB5B3EBFBAC6FA6C10E757DF71C1037 | 2026-08-19T04:48:47.0901735Z |
| models | gde_ap-v1-fp16-64x64-rev2-ox.tz2 | .tz2 | UNKNOWN | 633622 | 88CB4E45C85D42A33CFD03F40D65C9DAABB0C9185A37AAA2343D2E0AD332843D | 2026-08-19T04:52:45.8986137Z |
| models | gde_ap.json | .json | UNKNOWN | 1020 | B07FFD5493EF5710001364F964A9A8D67EC26285D5C6CD3545694B3484CD32F0 | 2026-08-12T12:33:16.0000000Z |
| models | gde-v1-fp16-192x192-1x-ov.tz2 | .tz2 | UNKNOWN | 65649533 | 019D71F12E288E0F92F7EB33E615C3562F36C6E212A1BB5578E7C0740CB0F7CD | 2026-08-19T04:49:13.3105562Z |
| models | gde-v1-fp16-192x192-2x-ov.tz2 | .tz2 | UNKNOWN | 66080841 | E0610ADF8F67C85181DC912671118ED0D0B73D3ACFCF8CB0AB88E49CFDB579FD | 2026-08-19T04:49:39.4516513Z |
| models | gde-v1-fp16-192x192-4x-ov.tz2 | .tz2 | UNKNOWN | 66361048 | D368A99FE56FEB8CC69F904935DED242813AB8CE81888C3CF9E602E5599799B4 | 2026-08-19T04:50:08.2126198Z |
| models | gde-v1-fp32-192x192-1x-ov.tz2 | .tz2 | UNKNOWN | 131187899 | 77EDCAB0F7246736BDD62EF2791EBD71D252114EBECFBEAE5D3E84E915B66ECF | 2026-08-19T04:50:59.9662618Z |
| models | gde-v1-fp32-192x192-2x-ov.tz2 | .tz2 | UNKNOWN | 132037018 | F1B5938ED22FDC3A1A52381F14F976B3879A09F38082825C101E5157041ECACB | 2026-08-19T04:51:51.8564306Z |
| models | gde-v1-fp32-192x192-4x-ov.tz2 | .tz2 | UNKNOWN | 132583932 | E2E8AE71CB6F0F42FA387287383D742C81CCE5D638D231562A1320331976574C | 2026-08-19T04:52:45.1365068Z |
| models | gde.json | .json | UNKNOWN | 7813 | CE24DA5019CBFE0F22E757C4D28F5EA87CF626E8F436BACD3B419847A25C82CC | 2026-08-12T12:33:16.0000000Z |
| models | gffm-v1-fp32-512x512-ov.tz2 | .tz2 | UNKNOWN | 52735577 | E426C446006891437E3111E3EE76C75F31787858606EFF8FF39576992807290E | 2026-08-19T04:53:08.2177888Z |
| models | gffm.json | .json | UNKNOWN | 2005 | 7D67ECAFDF6A578E3F0A838B1CFF755C56C2F98057271AEB01A492B83C56E8EC | 2026-08-12T12:33:16.0000000Z |
| models | gfg-v1-fp16-512x512-ov.tz2 | .tz2 | UNKNOWN | 171050878 | C242B262EA6E0B7E0902DBBAA0C2B4DA17E131FE42E38A61C2D9CDF8B99A2E7A | 2026-08-19T04:54:19.2577221Z |
| models | gfg.json | .json | UNKNOWN | 1779 | 65B70E7EC5CC74D570764343323E50911F62CEDDBD1B9856DB52C09941626FCB | 2026-08-12T12:33:16.0000000Z |
| models | gfp-l-v1-fp32-2048x2048-ov.tz2 | .tz2 | GFP | 112127097 | 7385754D4A912739E68D1D3B9EFF3940CD40468DFB7DC491C3CDDB8A9969AFB6 | 2026-08-19T04:55:06.5733309Z |
| models | gfp-l.json | .json | GFP | 1773 | 8AAA262B8A7A073CE1F49BC22712AA8D32F58A9A41ED7583F773CACC4E9A99B0 | 2026-08-12T12:33:18.0000000Z |
| models | gfp-s-v1-fp32-1024x1024-ov.tz2 | .tz2 | GFP | 110062102 | 4F1170581505D07039FBF3C14C7F75735023A97ED5CF3C6D5FFA10562B962319 | 2026-08-19T04:55:49.3745981Z |
| models | gfp-s.json | .json | GFP | 1773 | B6E1D6733773CEFBF2575326B759BF7B00D19837451F34503C0AA1F92E8DBBD8 | 2026-08-12T12:33:18.0000000Z |
| models | gfpf-v1-fp16-48x48-ov.tz2 | .tz2 | GFP | 801698 | 8FF5E06ACCE12711DF56FACD691CC21DDAC55DF3A4AD38BD43B15785BE43B9BA | 2026-08-19T04:55:50.0650452Z |
| models | gfpf.json | .json | GFP | 1741 | D0ECAF64C4647B372FD90333ADE90C62D66EC7070F5BDEAD07B7DDDA60CEF72B | 2026-08-12T12:33:18.0000000Z |
| models | gfrf-v2-fp16-1024x1024-ov.tz2 | .tz2 | UNKNOWN | 306429326 | D4C5A0BD200AD542EF1FAE1723D6AD4B3F71E2063DB0CDC664890CEC2E90D483 | 2026-08-19T04:57:46.5685120Z |
| models | gfrf.json | .json | UNKNOWN | 1762 | A462B74936C6B52D27F06471E8CE412FAF8D941C61F498B339F280B47EED7C4D | 2026-08-12T12:33:18.0000000Z |
| models | gfrg-v3-fp16-512x512-ov.tz2 | .tz2 | UNKNOWN | 189312280 | 6B304A8FFBC3918DAD1AD2F09B4CDD3F445D36EF4E4B698B231F1FD695F32B90 | 2026-08-19T04:59:23.6138577Z |
| models | gfrg.json | .json | UNKNOWN | 1706 | 1E22DC4D01DD0CD8EDE1A3EAF297F0B4E353931500E67F267616B3A3DA73AE9A | 2026-08-12T12:33:18.0000000Z |
| models | ggi-v1-fp16-192x192-2x-ov.tz2 | .tz2 | UNKNOWN | 66080841 | A2976B7314DD64EC0C88D0099A78DA6D6EEEDEF543D0C3F3B13E677354A10E51 | 2026-08-19T04:59:51.0216341Z |
| models | ggi-v1-fp16-192x192-4x-ov.tz2 | .tz2 | UNKNOWN | 66361048 | 74E32EAA2199414E58EC083FC57291B0A04BC5D22E5DE212657F6765B29CF841 | 2026-08-19T05:00:16.2092406Z |
| models | ggi-v1-fp32-192x192-2x-ov.tz2 | .tz2 | UNKNOWN | 132037018 | 962762F052C37592A9A4CDA7C3AEA561B51D7EB2E9160C82D34E358B3F21BA14 | 2026-08-19T05:01:07.2284830Z |
| models | ggi-v1-fp32-192x192-4x-ov.tz2 | .tz2 | UNKNOWN | 132583932 | D4B356A61029B1DCC9AF88FB7192FDFA25020C02EEFEFB229A789CB550B9292F | 2026-08-19T05:01:59.7726546Z |
| models | ggi.json | .json | UNKNOWN | 5731 | 54F689A545B1F49AB2A1F64A0B6E2B3A347E8656BF7D3FB8476697F6EED479EB | 2026-08-12T12:33:18.0000000Z |
| models | ggn_ap-v2-fp16-128x128-rev2-ox.tz2 | .tz2 | UNKNOWN | 1738244 | 37E35E17A630F2BF1CA1692B0292AEA1EE8FAFE3070AAFAEAB5A1B774023B4F9 | 2026-08-19T05:03:25.0495337Z |
| models | ggn_ap-v2-fp16-512x512-rev2-ox.tz2 | .tz2 | UNKNOWN | 1743549 | 12194E763ADE0AFB663423C929086808E739A02B7B94CA811D156C486575AE12 | 2026-08-19T05:03:26.0341333Z |
| models | ggn_ap.json | .json | UNKNOWN | 1041 | FE588B8D63554781BC7AEAB1D98C5F7C48E2016A4416E85062DB7F1F02DFB2A0 | 2026-08-12T12:33:18.0000000Z |
| models | ggn_noee.json | .json | UNKNOWN | 2106 | E83563E60E85CB9D707307D9BF60D119F44711E191BCF6F735E818D4E8590D69 | 2026-08-12T12:33:18.0000000Z |
| models | ggn-v3-fp16-128x128-2x-ov.tz2 | .tz2 | UNKNOWN | 109545893 | 1D7494E9F66AE95D7418BDAF39A34561AE5222B37307D471DE0EEA00A2189D96 | 2026-08-19T05:02:42.1878240Z |
| models | ggn-v3-fp16-128x128-4x-ov.tz2 | .tz2 | UNKNOWN | 109965439 | 4726D9D7BFAD4DE6B9C14833A91C1C754E123478A98E066D4340A459E551A95A | 2026-08-19T05:03:23.9712461Z |
| models | ggn.json | .json | UNKNOWN | 4964 | DCA872D7FE5090162F429DAD9554EBB7A94C2FB8FDE2E10A4BD9788DEFA1AACE | 2026-08-12T12:33:18.0000000Z |
| models | ggnv2-v3-fp16-128x128-2x-rev2-ov.tz2 | .tz2 | UNKNOWN | 109539201 | 7B39EB4005736F09858177571DDF000388419515A7EC8A6A3E578CA11C3E230A | 2026-08-19T05:04:14.6071112Z |
| models | ggnv2-v3-fp16-128x128-4x-rev2-ov.tz2 | .tz2 | UNKNOWN | 111035335 | 11D2333F724A4E46CF947CBF281F4945D027DA807B9A28CDA2B0D2E9607C0D82 | 2026-08-19T05:04:57.1395739Z |
| models | ggnv2.json | .json | UNKNOWN | 4920 | 9CCFD57AF7469A40F62C4250F67F973DE0DFD91D3E07E2E6A8941ABA4DCA543E | 2026-08-12T12:33:18.0000000Z |
| models | ghc-v2-fp16-192x192-1x-ov.tz2 | .tz2 | UNKNOWN | 65702758 | 578509140F4030518438168CF8AEE940A51DE3DCCFD34333BC6ADBADBB3579CE | 2026-08-19T05:05:23.1713908Z |
| models | ghc-v2-fp16-192x192-2x-ov.tz2 | .tz2 | UNKNOWN | 66150173 | 62C21A3241BF135557F9CEF1EE55513FBCC8C9B42CF4C7FCE4EEA7CDDD275997 | 2026-08-19T05:05:48.7098955Z |
| models | ghc-v2-fp16-192x192-4x-ov.tz2 | .tz2 | UNKNOWN | 66446409 | 2812B38369BE39E913DDDD27FC82381DC4D3A437F2D43A57C786E76BFEC75090 | 2026-08-19T05:06:14.5761997Z |
| models | ghc-v2-fp32-192x192-1x-ov.tz2 | .tz2 | UNKNOWN | 131241140 | 03485009B0AC6E03AF05251261C2C986A4134F518CE9BCEDF30C90D8983CA7B3 | 2026-08-19T05:07:04.8252674Z |
| models | ghc-v2-fp32-192x192-2x-ov.tz2 | .tz2 | UNKNOWN | 132106368 | DAEDA6D930FC974694971A8FE40F794C07B23ECC1143D7D30E95B6D3F3DB4E40 | 2026-08-19T05:07:55.0143108Z |
| models | ghc-v2-fp32-192x192-4x-ov.tz2 | .tz2 | UNKNOWN | 132669315 | 69C09C1CC4BD54002ECE5DC3832F42884D5A830DC93204931167AD8D89E5B372 | 2026-08-19T05:08:45.7303269Z |
| models | ghc.json | .json | UNKNOWN | 7946 | F41846F0545CC7790CB286E93D30501ACC86F21378FDB39107D53B56ACAD51D4 | 2026-08-12T12:33:18.0000000Z |
| models | ghq_noee.json | .json | UNKNOWN | 2118 | 3C6DE6C08146F1C6F58364D7A32E3372F0F62853A55AB891C51941A712CBB63A | 2026-08-12T12:33:18.0000000Z |
| models | ghq-v1-fp16-96x96-2x-ov.tz2 | .tz2 | UNKNOWN | 109392953 | E10C6053C279B71076419252BEB1CA36AD3700824568D80D02D2FE41A560B7FA | 2026-08-19T05:09:27.5501998Z |
| models | ghq-v1-fp16-96x96-4x-ov.tz2 | .tz2 | UNKNOWN | 109697809 | EF181574F439AF896CEEF052339DAD5B607F568B27000A7B9403A6AD299C609A | 2026-08-19T05:10:09.7989592Z |
| models | ghq.json | .json | UNKNOWN | 4960 | F40A18B5A194DCE78DDB59AFC3DEDF11193CFF0F56C32E6BBA2828D4DBCD930E | 2026-08-12T12:33:18.0000000Z |
| models | ghqv2_ldn-v1-fp16-128x128-2x-rev2-ov.tz2 | .tz2 | UNKNOWN | 109539201 | 4049CCAC09865025FAB9B78CF7892687C9AA9B20B893ADF3996169EE3E89F95D | 2026-08-19T05:12:37.5352237Z |
| models | ghqv2_ldn-v1-fp16-128x128-4x-rev2-ov.tz2 | .tz2 | UNKNOWN | 111035335 | D9A5864DC965095F4F721BB69849278B02E1850BACF354640C7E0B8635DC5920 | 2026-08-19T05:13:27.2368459Z |
| models | ghqv2_ldn.json | .json | UNKNOWN | 4826 | A19EB6E3E9F6412F0A475034827CAA8B4F3C51EEA4D6E678344075DED8177833 | 2026-08-12T12:33:18.0000000Z |
| models | ghqv2-v1-fp16-128x128-2x-rev2-ov.tz2 | .tz2 | UNKNOWN | 109539201 | 619102DE93A4BA537955F26854AAF369F909F69C89639E53E4B5817C3FF811CF | 2026-08-19T05:10:52.4682349Z |
| models | ghqv2-v1-fp16-128x128-4x-rev2-ov.tz2 | .tz2 | UNKNOWN | 111035335 | 51138D030436CA24E3F88B9739492B1AB19F766ED61C73A0DCDB2D16A3590580 | 2026-08-19T05:11:45.8287905Z |
| models | ghqv2.json | .json | UNKNOWN | 5019 | 7552F0390C0B89ED381BDDA3F4F56449851EE598B080F968E817C32F42BF8C1F | 2026-08-12T12:33:18.0000000Z |
| models | ghqv3_cache-v2-fp16-224x224-ox.tz2 | .tz2 | UNKNOWN | 33862464 | 477A4A2AA956EB2EECE91D7B230024600D83D2071C265E1CF00EA0EDEA243388 | 2026-08-19T05:14:52.0060210Z |
| models | ghqv3_cache.json | .json | UNKNOWN | 1522 | CEEB6FEBB454729F0F7AC9FD95AF0CF46F2C1B303492226C3B6AAEA4DA078115 | 2026-08-12T12:33:18.0000000Z |
| models | ghqv3-v2-fp16-512x512-rev1-ox.tz2 | .tz2 | UNKNOWN | 153756209 | 3601FF420E8C7DD720E65E4D18C098BA26B70D70EA78BF026D383307227BE60D | 2026-08-19T05:14:33.5483372Z |
| models | ghqv3.json | .json | UNKNOWN | 1551 | 38E51E88B7B238112E42497CEB1AB04B6F6DC51011BA3129EF986BC91A3D9E35 | 2026-08-12T12:33:18.0000000Z |
| models | gmp-v1-fp16-192x192-2x-ov.tz2 | .tz2 | GMP | 66080841 | 580D6BA5629A2F621003D5692602A1E222995BE8A23E7BFD972E921FE2F533FA | 2026-08-19T07:45:08.7153911Z |
| models | gmp-v1-fp16-192x192-4x-ov.tz2 | .tz2 | GMP | 66361048 | B890997FFCECC44F7433B84A627016FE742C619573A95BAD037C8B4ECBC3C8EE | 2026-08-19T05:15:55.7193909Z |
| models | gmp-v1-fp32-192x192-2x-ov.tz2 | .tz2 | GMP | 132037018 | 854456A6BD93A2A7DB1BE92364FE9E635D20C3B72D653EF73B6EC2433CF67621 | 2026-08-19T07:46:01.2465986Z |
| models | gmp-v1-fp32-192x192-4x-ov.tz2 | .tz2 | GMP | 132583932 | 03189A1DB9C45FA1D8BF3D77A22D03161083F773AA9786B0B7D9AC7C36E15DBA | 2026-08-19T05:19:12.3005601Z |
| models | gmp.json | .json | GMP | 5771 | 806CA83F232A357B5955B97A488A5E83BCCAB9ED52C48C42C690D5FA632DD521 | 2026-08-12T12:33:20.0000000Z |
| models | gmpv2-v13-fp16-192x192-2x-ov.tz2 | .tz2 | GMP | 109973715 | 4F4F3A3215F4CDBBD2097C163D6E97158FA42A5CC4495228CC9EC3D9E112CE91 | 2026-08-19T05:19:59.6423276Z |
| models | gmpv2-v13-fp16-192x192-4x-ov.tz2 | .tz2 | GMP | 112780571 | 32A14BD01B37873155AFED9B9350FBB1E5DC9714824D86FBCD615B7228DFEA2C | 2026-08-19T05:20:55.1210844Z |
| models | gmpv2.json | .json | GMP | 5007 | 6755BD78F7F09ABB805B96128A5762CDCAC938618A2E0DFDD0E30D5E651E0258 | 2026-08-12T12:33:20.0000000Z |
| models | irwn_dec-v2-fp32-64x64-ox.tz2 | .tz2 | IRWN | 1067980 | 26F1F0144391F99582D0D0CB8046877FEFF616C29137B96054CE2F6D4E54633F | 2026-08-19T05:20:55.9882569Z |
| models | irwn_dec-v2-fp32-64x64.onnx.data | .data | IRWN | 286588928 | CCD954971547E862E58A23E4F9EF8E9B7997710369410B57DA1C81FA78BF09BB | 2026-08-19T05:23:33.6303294Z |
| models | irwn_dec.json | .json | IRWN | 1455 | 1C881C2D710C31CDC5A619A7F7BF3F7A59F5EC9C81231831FE3FCF55E127C388 | 2026-08-12T12:33:20.0000000Z |
| models | irwn_dit-v2-fp32-128x128-ox.tz2 | .tz2 | IRWN | 9133145 | 39BF3967AB3BE51950A3825C6CD47F15377FE92D0317C1ED62DA15497C2F07D4 | 2026-08-19T05:23:40.6347409Z |
| models | irwn_dit-v2-fp32-128x128.onnx.data | .data | IRWN | 5680660480 | BF93688C9C3CAAF2C5069582109BEDFC15C54479F70F99EFE9CC716ED38CB793 | 2026-08-19T06:05:17.9033117Z |
| models | irwn_dit.json | .json | IRWN | 2307 | 0269EFE9B3207C2018A5D778D647819FF9E018D96711482317F7D1147D72D22C | 2026-08-12T12:33:20.0000000Z |
| models | irwn_enc-v2-fp32-512x512-ox.tz2 | .tz2 | IRWN | 674814 | 085B0FEA932B05A975D53CB3343EE83353795AC36355C6C2394407245FC1DA78 | 2026-08-19T06:05:19.5670242Z |
| models | irwn_enc-v2-fp32-512x512.onnx.data | .data | IRWN | 212402176 | 0E706BEA019A8416BA8F5E273914926E4B446B4CCA40E59284FEE83FCAF295DD | 2026-08-19T06:06:51.6984309Z |
| models | irwn_enc.json | .json | IRWN | 1488 | 034FA535792B50F7CE2C2B427017243EEC0862A3A980AD96438C087857B8D2EA | 2026-08-12T12:33:20.0000000Z |
| models | ldclc-v1-fp16-64x64-ov.tz2 | .tz2 | LDCLC | 20213 | E07CA2C3B88377EAA8D293B5537BDAF08A78A8EB88DC8A0983D435F683168244 | 2026-08-19T06:06:53.3695573Z |
| models | ldclc-v1-fp16-64x64-ox.tz2 | .tz2 | LDCLC | 88337 | F198AD5852348FE53C208E82FA7E934B301B3C989A965F9FAFCAE62A8E94D812 | 2026-08-19T06:06:54.1393602Z |
| models | ldclc-v1-fp16-96x96-ox.tz2 | .tz2 | LDCLC | 82462 | D7D40413802F17C924E15430C1D654EE7EAFBCF1E62A6F39160E9CAB795E9463 | 2026-08-19T06:06:54.9314885Z |
| models | ldd21-v2-fp16-64x64-ov.tz2 | .tz2 | UNKNOWN | 99359177 | 104DBFA4E737F4B8A1A73AECD486887D98F8474F396F0FD22B83F4F689B7285C | 2026-08-19T06:07:42.0859307Z |
| models | ldd21.json | .json | UNKNOWN | 2749 | FA032CD7C831AD1800CB495B948339F24D9FBCC62D95B10B4B7BC5F6DBBC4D4D | 2026-08-12T12:33:20.0000000Z |
| models | lddv21_noclc.json | .json | UNKNOWN | 2222 | AB5BC564EE7D96BA578683B0630EA666CDAF210AAD50E94DA19DC6E21D51ED45 | 2026-08-12T12:33:20.0000000Z |
| models | lddv21-v1-fp16-64x64-ov.tz2 | .tz2 | UNKNOWN | 99359178 | E0D3F38152754021BFD8109E1742ECFD01C50C776D2A110225E963D38C556362 | 2026-08-19T06:08:29.4559135Z |
| models | lddv21.json | .json | UNKNOWN | 2751 | 77CFDA82C897A91E3E079BB8C24F11CC2EE2E5570A9420953BB17CF2DBA87B6A | 2026-08-12T12:33:20.0000000Z |
| models | lde21-v1-fp16-512x512-ov.tz2 | .tz2 | UNKNOWN | 68654222 | 75B5D5B6A2A48C09D1E29E938897C3E77262258AB7EA818F1EF81EB81FF1D6FE | 2026-08-19T06:09:03.1742642Z |
| models | lde21.json | .json | UNKNOWN | 2245 | 3E19FC88CC92C22B3CB6F670EBC6C28CEAB603FF8BF813BE184BCCB08910AA91 | 2026-08-12T12:33:20.0000000Z |
| models | ldu21-v2-fp16-64x64-ov.tz2 | .tz2 | UNKNOWN | 2394200723 | 9FF94F75400061DEA16CBDF0EF5C5E90CC56F32F282CBC317DDE98620938CA4B | 2026-08-19T06:26:23.7144942Z |
| models | ldu21.json | .json | UNKNOWN | 2250 | 24D2CEFA072F8F4C3931F207D3F26DFC209C87C78B37F9D4D916910A92A18ABB | 2026-08-12T12:33:20.0000000Z |
| models | neg_emb.yaml | .yaml | UNKNOWN | 1746924 | 4EA8205B9156271A8B13BED64BD0A8C74FF25246B379DB2DE8B762B0693CD9B0 | 2026-08-19T06:26:25.1482367Z |
| models | neuroserver.json | .json | UNKNOWN | 836 | 448D9BB2E50DF5B8689FFD1D417C32F2E4CCBFB1F25F2BF91F284BE0FA084D1B | 2026-08-12T12:33:20.0000000Z |
| models | rxl_decoder0-v1-fp16-96x96-ox.tz2 | .tz2 | UNKNOWN | 99040065 | D413A9DA161CA22D97A53CAFA7189263B0199A813AA037DFBED8DC8AFAF99CD6 | 2026-08-19T06:27:08.2528365Z |
| models | rxl_decoder0.json | .json | UNKNOWN | 2377 | 9D461A62BA51FFA7391F3D71DCFC7BB690F3FD097CBA379F5E5FB30E4CD28F8E | 2026-08-12T12:33:20.0000000Z |
| models | rxl_decoder1-v1-fp16-120x120-ox.tz2 | .tz2 | UNKNOWN | 99040065 | BCCFE54D161EA6853455F5C2D6963A0C93AEB2F69DDFD51D6D04FA5A8921AAC6 | 2026-08-19T06:27:54.2258911Z |
| models | rxl_decoder1.json | .json | UNKNOWN | 2023 | E5FAAFB3C794C85857A9B0FFF751080CBA182D7FC794645395F499E08A8DC571 | 2026-08-12T12:33:20.0000000Z |
| models | rxl_embed-v1-fp16-77x768-ox.tz2 | .tz2 | UNKNOWN | 246317314 | 3A4DCB2BB6E4A110524028D12B52EC083BDB92869B7A290DDFD107F0AE263DE7 | 2026-08-19T06:29:45.1110694Z |
| models | rxl_embed.json | .json | UNKNOWN | 1680 | 4608C7185C7F24A3B6C3862D35958731C9F9D9D701D5B001CCB5794990A14525 | 2026-08-12T12:33:20.0000000Z |
| models | rxl_encoder0-v1-fp16-768x768-ox.tz2 | .tz2 | UNKNOWN | 68397977 | 46628A31BDECF462B1F567EE624DD05C81645B78251C407AB078DFF076EF5E02 | 2026-08-19T06:30:16.8545596Z |
| models | rxl_encoder0.json | .json | UNKNOWN | 1938 | EDDE22EE93E9029A2DB0D9DCC70233419AAD06FAE9293D8EB1D6CA98643D557F | 2026-08-12T12:33:22.0000000Z |
| models | rxl_encoder1-v1-fp16-960x960-ox.tz2 | .tz2 | UNKNOWN | 68397977 | 3A2E850ECDBDB47250B3182615F772DC1DC3800C7B71569401C80B6977B2292F | 2026-08-19T06:30:46.7391794Z |
| models | rxl_encoder1.json | .json | UNKNOWN | 1941 | 51F74580D821E9C972D7A8C4A2B124C611233FC294942656609EB64A6D4E8763 | 2026-08-12T12:33:22.0000000Z |
| models | rxl_merges.txt | .txt | UNKNOWN | 524619 | 9FD691F7C8039210E0FCED15865466C65820D09B63988B0174BFE25DE299051A | 2026-08-19T06:30:47.5351694Z |
| models | rxl_unet0-v2-fp16-ox.tz2 | .tz2 | UNKNOWN | 1561984 | 2A75C210CE1583154DE795DC0982B42493E8B56EB781C41E7249CA9C69B7B370 | 2026-08-19T06:30:48.5762879Z |
| models | rxl_unet0-v2-fp16.pb | .pb | UNKNOWN | 2439033600 | BE0A3A6AA3DA599D6D8A55EA7BECB84CE167E73D6017DB5C8DDA2C147C849FBA | 2026-08-19T06:48:45.1986793Z |
| models | rxl_unet0.json | .json | UNKNOWN | 1159 | 6BFD3932CE7263D6AC685DAEDEBA9E6D7F3D25D4E270CCD224C2AE9B8A876CE3 | 2026-08-12T12:33:22.0000000Z |
| models | rxl_unet1-v2-fp16-ox.tz2 | .tz2 | UNKNOWN | 1528559 | 42BAD34FD34F8EF2FAD562101E4FF95A6D42F9B5083FEF415945422068551BF2 | 2026-08-19T06:48:46.5302632Z |
| models | rxl_unet1-v2-fp16.pb | .pb | UNKNOWN | 2441165568 | DB490B2F11711CEAFCA4B02F8FFA0A1BEAB03CA529C2650EDEA506CAB6AE9586 | 2026-08-19T07:06:27.0721477Z |
| models | rxl_unet1.json | .json | UNKNOWN | 1160 | 00CB4CD7C586C45015B0B6068C0087A667D77F8E9F4FC7AA4CBC70119D524B3A | 2026-08-12T12:33:22.0000000Z |
| models | rxl_vocab.txt | .txt | UNKNOWN | 1059962 | E089AD92BA36837A0D31433E555C8F45FE601AB5C221D4F607DED32D9F7A4349 | 2026-08-19T07:06:29.6071795Z |
| models | slsp_ap-v2-fp16-512x512-rev2-ox.tz2 | .tz2 | UNKNOWN | 1761841 | F20976BE6BB9C825E3F891B4A5EAB00373BB323ECBF1D93C1554D8FA998AB005 | 2026-08-19T07:06:30.6885799Z |
| models | ssddec0_0-v1-fp16-64x64-ov.tz2 | .tz2 | SSD | 99239881 | FB44EC6CAF7C244292D9F679C678D793F0D45A2A5EB4B372F06F78BA41F44617 | 2026-08-19T07:07:11.6214648Z |
| models | ssddec0_0.json | .json | SSD | 2529 | 9F647877A01B4056D1A4982CD99AAEC59AF43335AD083FAE182648955AB19650 | 2026-08-12T12:33:24.0000000Z |
| models | ssddec0_5-v1-fp16-64x64-ov.tz2 | .tz2 | SSD | 99239881 | 45256C1F2EBCD0352B3747BFBC026AD2F5A93B6482480901F520679EF9127B82 | 2026-08-19T07:07:56.1281130Z |
| models | ssddec0_5.json | .json | SSD | 2529 | BF3AC17274498EBFF22A1C1AB4FB1B2B1E816944EB4BEB11DC8508B220301DD3 | 2026-08-12T12:33:24.0000000Z |
| models | ssddec1_0-v1-fp16-64x64-ov.tz2 | .tz2 | SSD | 99239881 | CA406290B155A97D4C715BEE8FBAAE97B3CB3FE5B8D72D925601B8DE0F16E862 | 2026-08-19T07:08:43.3991206Z |
| models | ssddec1_0.json | .json | SSD | 2530 | 27CC83A3DC3A5390F4ECF26F258A282B144BC644E1E21C7A618EEBD3F21E9480 | 2026-08-12T12:33:24.0000000Z |
| models | ssdenc-gpu-mac.json | .json | SSD | 784 | D74CECA31F95F95D95BE00ECAC0DA28F2AC8C6C6CA5BDC1883090BA34E9F32FB | 2026-08-12T12:33:24.0000000Z |
| models | ssdenc-v1-fp16-512x512-ov.tz2 | .tz2 | SSD | 68554700 | 85E866FB8543C295F53F9E0B1B7E27E654973CC365E86957070C3CC2C7AFCB0D | 2026-08-19T07:09:11.9349252Z |
| models | ssdenc.json | .json | SSD | 1939 | 7D9FC1002B24D80346204CAE0F6B4B42B69B5801C2C3E5F0CD598BEF2D3321CC | 2026-08-12T12:33:24.0000000Z |
| models | ssdunet-gpu-mac.json | .json | SSD | 737 | 93CA0FE3D28FD550506446FA13D18AE5CC5846BCB3016B2C4BB4B45FA209B861 | 2026-08-12T12:33:24.0000000Z |
| models | ssdunet-v1-fp16-64x64-ov.tz2 | .tz2 | SSD | 1733588632 | 8D6498E4E82B2FD3364CCF02E5615256B9D9C89D043BFFD2AA6506B4414C55CF | 2026-08-19T07:22:30.2274973Z |
| models | ssdunet.json | .json | SSD | 1994 | E3D2317AF085016221CE0494E75586F0C5B9D722708547B1CD4669055CEA5E2B | 2026-08-12T12:33:24.0000000Z |
| models | stdmax_noee.json | .json | UNKNOWN | 703 | CAADF6E503348CF9EE8EEEC280A4A0E2BC59DE11ADAA407C5FA11CF7CF66F5FF | 2026-08-12T12:33:24.0000000Z |
| models | stdmax-v1-fp16-192x192-ov.tz2 | .tz2 | UNKNOWN | 1713534145 | C849846E5D7E1A8FC4D499F24C2CF198DF79802C668A2945E692CE4CBBE4F804 | 2026-08-19T07:58:27.7795822Z |
| models | stdmax.json | .json | UNKNOWN | 1803 | 241BDCE98D97E12CAEC1EEFC924235249A79DBE8D9EC035971C3E4DA72067403 | 2026-08-12T12:33:24.0000000Z |
| models | tpn_900_nogpu.json | .json | UNKNOWN | 1144 | B51237C0F604FE6C1D0E82EC19E388E611DFDF6394CF26E583CD3220A8B72674 | 2026-08-12T12:33:26.0000000Z |
| models | tpn_900.json | .json | UNKNOWN | 1133 | 568BC14DA7C5E19DC324CC575D98FB485A2B43FEF87240BBA666A69F26E1443E | 2026-08-12T12:33:24.0000000Z |
| models | tpn_dec-v1-fp16-64x64-ox.tz2 | .tz2 | UNKNOWN | 99145391 | 0DC1FA05B33DFE78BAFEEFF6788082C25E9AAC01F1622E09543B11FB655E6B10 | 2026-08-19T07:31:09.0037650Z |
| models | tpn_embeds.bin | .bin | UNKNOWN | 473088 | D924469A4405DB6044881DB289DBDC2183BD0DD125FC70F8028A1914D31371C6 | 2026-08-19T07:31:09.9433683Z |
| models | tpn_enc-v1-fp16-512x512-ox.tz2 | .tz2 | UNKNOWN | 68478821 | D6964C56FCDE5043BD405D6B99D14795F3E2637D9BDB5C07F3C28CAA61DED406 | 2026-08-19T07:31:37.7506539Z |
| models | tpn_nogpu.json | .json | UNKNOWN | 1141 | C279F784273E6D68F0880C4DACC8A55B5B8FE178C7B6BEC5A658980F0A832113 | 2026-08-12T12:33:26.0000000Z |
| models | tpn_unet-v1-fp16-64x64-ox.tz2 | .tz2 | UNKNOWN | 1720324834 | E4A04E101FCCEC4D8D946E2E7AB1B85FBCC4D54C02BE71AFF08A5BE48D55A2F8 | 2026-08-19T07:43:59.9882663Z |
| models | tpn.json | .json | UNKNOWN | 2249 | 974B2971A0FB49685BAA217AD66BD967FC18A619439EB434EF31365CFAFCA974 | 2026-08-12T12:33:24.0000000Z |
| models | trf-v1-fp16-128x128-2x-ov.tz2 | .tz2 | TRF | 34612386 | F2F0A8905790A437EAFBD9C6AA6198D0F5C6AA730D0C490ED8CDF2AC9AFE27EE | 2026-08-19T07:44:14.1880963Z |
| models | trf-v1-fp16-128x128-4x-ov.tz2 | .tz2 | TRF | 34695138 | A88381F229C758B0C92911442770A8E28B46B7C06E8F6BDABCE678537A4EBD9B | 2026-08-19T07:44:28.4848148Z |
| models | trf.json | .json | TRF | 4935 | 9131747D307F976F9C25689838A3D0747FFF16FBFDA9C365E5DC74B4AEE17D64 | 2026-08-12T12:33:26.0000000Z |
| models | trfn-v1-fp16-512x512-1x-ov.tz2 | .tz2 | TRF | 34747554 | B84F009E630E4B04B3453196453AD2F30781987EDC396CBD53BEE49C1802EF9D | 2026-08-19T07:44:43.0077131Z |
| models | trfn.json | .json | TRF | 2934 | 89CFF8D1A6CF446D5030F29C958EA6DF0D487B076BC0E91854981944E66AAB7F | 2026-08-12T12:33:26.0000000Z |
| models | wonder-2.json | .json | Wonder | 1670 | F70A5D9078884AFB185D26B3F9257C51057A891ABE5DAC1486C111E017D82080 | 2026-08-12T12:33:26.0000000Z |
| models | wonder-3.5.json | .json | Wonder | 517 | 0CAA353BC0F51404F9FEA50425B1BDD33A3A6A95BF483004034FCB01CDCA5892 | 2026-08-12T12:33:26.0000000Z |
| models | wonder-3.json | .json | Wonder | 1874 | 919C30F8455EB1A6547F928806DFB77DF5ABC87EBF37A8D4EE20DF480996330D | 2026-08-12T12:33:26.0000000Z |
| models | wonder-all.json | .json | Wonder | 1877 | A2CCE2BBCD9449F312C916C6ECC58DA31D1890198661705338B97585540ED78F | 2026-08-12T12:33:26.0000000Z |
| logs | 2026-08-19-12-51-55.tzlog | .tzlog | N/A | 347 | C8BC4AE075612CC0B5BCD2588403B1E730191CA3DE5C202C404C3AC0110257C7 | 2026-08-19T04:51:55.2958838Z |
| logs | 2026-08-20-12-19-1.tzlog | .tzlog | N/A | 20012 | 23D457C31E086F686E6F82A85424F916A411DB7EEA8955D4D1F5918EF5B86DBD | 2026-08-20T04:20:21.9996760Z |
| logs | 2026-08-20-12-19-11.tzlog | .tzlog | N/A | 1753 | F4F1468307D539F8E2900917C5F0CA3093CAFC4ECDBAC7C2DA2EFDBB35204627 | 2026-08-20T04:19:11.4731846Z |
| logs | 2026-08-20-12-20-23.tzlog | .tzlog | N/A | 18763 | 60BC9C59D5D920291B86A433ECE2176C73B0BAAE2E55FE976EC8A54DC63FCBC6 | 2026-08-20T04:40:28.1116036Z |
| logs | Installer-2026-08-19_15-58-34.log | .log | N/A | 83 | 1645EC116CAE752283C95A9B773AF7B8F8FBA0D5DBFD32F4AFA159C06FBA1282 | 2026-08-19T07:58:34.1210818Z |
| logs | lastSessionFiles.txt | .txt | N/A | 0 | NOT_COMPUTED_NOT_AUTHORIZED | 2026-08-20T04:40:27.7479475Z |
| logs | Topaz Gigapixel Installer Log.txt | .txt | N/A | 6918506 | NOT_COMPUTED_NOT_AUTHORIZED | 2026-08-19T07:58:31.3756324Z |

## 5. JSON 完整解析

本节包含全部 60 个 JSON。每个配置均给出基础字段、inputs 完整键值映射、逐 backend/scale 的精确矩阵，以及无字段省略的完整解析对象。`null` 表示源配置缺失该字段，不作猜测。

### ap_all.json

#### 基础信息

```json
{
  "name": null,
  "shortName": "ap_all",
  "category": null,
  "version": "2",
  "enabled": 3,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "input",
  "ggn_gamma": "gamma",
  "mask": "dummy"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imap` | 0 | 1 | `["ggn_ap-v2-fp16-[H]x[W]-rev2-mlc.tz","apnb-v2-fp16-[H]x[W]-rev2-mlc.tz","slsp_ap-v2-fp16-[H]x[W]-rev2-mlc.tz"]` | `[512,512]` | `["output","output","output"]` |
| openvino | `imap` | 0 | 1 | `["ggn_ap-v2-fp16-[H]x[W]-rev2-ox.tz2","apnb-v2-fp16-[H]x[W]-rev2-ox.tz2","slsp_ap-v2-fp16-[H]x[W]-rev2-ox.tz2"]` | `[512,512]` | `["output","output","output"]` |
| onnx | `imap` | 0 | 1 | `["ggn_ap-v2-fp16-[H]x[W]-rev2-ox.tz2","apnb-v2-fp16-[H]x[W]-rev2-ox.tz2","slsp_ap-v2-fp16-[H]x[W]-rev2-ox.tz2"]` | `[512,512]` | `["output","output","output"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "2",
  "shortName": "ap_all",
  "enabled": 3,
  "optional": 0,
  "padding": [
    0,
    0
  ],
  "parameterNames": [
    "param2",
    "param1",
    "param3",
    "noise",
    "blur",
    "slsp_noise",
    "lensblur",
    "motionblur",
    "compression"
  ],
  "inputs": {
    "input": "input",
    "ggn_gamma": "gamma",
    "mask": "dummy"
  },
  "backends": {
    "coreml": {
      "model": "imap",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "ggn_ap-v2-fp16-[H]x[W]-rev2-mlc.tz",
            "apnb-v2-fp16-[H]x[W]-rev2-mlc.tz",
            "slsp_ap-v2-fp16-[H]x[W]-rev2-mlc.tz"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "output",
            "output",
            "output"
          ]
        }
      }
    },
    "openvino": {
      "model": "imap",
      "parallel": 0,
      "transpose": 0,
      "scales": {
        "1": {
          "nets": [
            "ggn_ap-v2-fp16-[H]x[W]-rev2-ox.tz2",
            "apnb-v2-fp16-[H]x[W]-rev2-ox.tz2",
            "slsp_ap-v2-fp16-[H]x[W]-rev2-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "output",
            "output",
            "output"
          ]
        }
      }
    },
    "onnx": {
      "model": "imap",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "ggn_ap-v2-fp16-[H]x[W]-rev2-ox.tz2",
            "apnb-v2-fp16-[H]x[W]-rev2-ox.tz2",
            "slsp_ap-v2-fp16-[H]x[W]-rev2-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "output",
            "output",
            "output"
          ]
        }
      }
    }
  }
}
```

</details>

### claa.json

#### 基础信息

```json
{
  "name": "Color Light General",
  "shortName": "claa",
  "category": "Exposure Adjust",
  "version": "1",
  "enabled": 3,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "netInput"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | 1 | 1 | `"[N]-v[V]-fp32-[H]x[W]-rev1-mlc.tz"` | `[512,512]` | `"netOutput"` |
| onnx | `imn` | 1 | 1 | `"[N]-v[V]-fp32-[H]x[W]-ox.tz2"` | `[512,512]` | `"netOutput"` |
| openvino | `imn` | 1 | 1 | `"[N]-v[V]-fp32-[H]x[W]-ov.tz2"` | `[512,512]` | `"netOutput"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "claa",
  "name": "Color Light General",
  "category": "Exposure Adjust",
  "verb": "Adjusting lighting",
  "enabled": 3,
  "optional": 0,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 0,
  "blockDiscard": 0,
  "inputs": {
    "input0": "netInput"
  },
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": 1,
      "minMacVersion": 10.16,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "openvino": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    }
  }
}
```

</details>

### gde_ap.json

#### 基础信息

```json
{
  "name": null,
  "shortName": "gde_ap",
  "category": null,
  "version": "1",
  "enabled": 1,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "input"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imap` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev2-mlc.tz"` | `[64,64]` | `"output"` |
| openvino | `imap` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev2-ox.tz2"` | `[64,64]` | `"output"` |
| onnx | `imap` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev2-ox.tz2"` | `[64,64]` | `"output"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "shortName": "gde_ap",
  "enabled": 1,
  "optional": 0,
  "padding": [
    0,
    0
  ],
  "parameterNames": [
    "param1",
    "param2"
  ],
  "inputs": {
    "input": "input"
  },
  "backends": {
    "coreml": {
      "model": "imap",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev2-mlc.tz"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "output"
          ]
        }
      }
    },
    "openvino": {
      "model": "imap",
      "parallel": 1,
      "transpose": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev2-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "output"
          ]
        }
      }
    },
    "onnx": {
      "model": "imap",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev2-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "output"
          ]
        }
      }
    }
  }
}
```

</details>

### gde.json

#### 基础信息

```json
{
  "name": "Compression",
  "shortName": "gde",
  "category": "Enhance",
  "version": "1",
  "enabled": 1,
  "optional": 1,
  "autoModel": "gde_ap"
}
```

#### inputs 完整映射

```json
{
  "param1": "t_param",
  "param2": "t_param1",
  "input": "netInput",
  "cinput": "infer_input",
  "output": "infer_output",
  "gamma": "dummy"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 1 | 1 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["tl_unet1x2x4x/out1x/add_2","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["tl_unet1x2x4x/out2x/add_2","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["tl_unet1x2x4x/out4x/add_2","model/tf.clip_by_value/clip_by_value"]` |
| openvino16 | `imcc` | 1 | 1 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["tl_unet1x2x4x/out1x/add_2","model/tf.clip_by_value/clip_by_value"]` |
| openvino16 | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["tl_unet1x2x4x/out2x/add_2","model/tf.clip_by_value/clip_by_value"]` |
| openvino16 | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["tl_unet1x2x4x/out4x/add_2","model/tf.clip_by_value/clip_by_value"]` |
| onnx | `imcc` | 1 | 1 | `["[N]-v2-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput1X","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 2 | `["[N]-v2-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput2X","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 4 | `["[N]-v2-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput4X","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 1 | `["[N]-v2-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput1X","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 2 | `["[N]-v2-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput2X","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 4 | `["[N]-v2-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput4X","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 1 | `["[N]-v2-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput1X","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 2 | `["[N]-v2-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput2X","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 4 | `["[N]-v2-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput4X","tf.clip_by_value"]` |
| coreml | `imcc` | 1 | 1 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[192,192]` | `["tl_unet1x2x4x/netOutput1X","Identity"]` |
| coreml | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[192,192]` | `["tl_unet1x2x4x/netOutput2X","Identity"]` |
| coreml | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[192,192]` | `["tl_unet1x2x4x/netOutput4X","Identity"]` |
| tensorrt | `imcc` | 1 | 1 | `["[N]-v2-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[192,192]` | `["netOutput1X","tf.clip_by_value"]` |
| tensorrt | `imcc` | 1 | 2 | `["[N]-v2-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[192,192]` | `["netOutput2X","tf.clip_by_value"]` |
| tensorrt | `imcc` | 1 | 4 | `["[N]-v2-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[192,192]` | `["netOutput4X","tf.clip_by_value"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "uiVersion": "1",
  "minAppVersion": "5.5.0",
  "shortName": "gde",
  "enabled": 1,
  "optional": 1,
  "name": "Compression",
  "category": "Enhance",
  "verb": "Enhancing",
  "autoModel": "gde_ap",
  "zeroCenter": 3,
  "inputs": {
    "param1": "t_param",
    "param2": "t_param1",
    "input": "netInput",
    "cinput": "infer_input",
    "output": "infer_output",
    "gamma": "dummy"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/out1x/add_2",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/out2x/add_2",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/out4x/add_2",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "openvino16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/out1x/add_2",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/out2x/add_2",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/out4x/add_2",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v2-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput1X",
            "tf.clip_by_value"
          ]
        },
        "2": {
          "nets": [
            "[N]-v2-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput2X",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v2-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput4X",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v2-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput1X",
            "tf.clip_by_value"
          ]
        },
        "2": {
          "nets": [
            "[N]-v2-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput2X",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v2-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput4X",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v2-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput1X",
            "tf.clip_by_value"
          ]
        },
        "2": {
          "nets": [
            "[N]-v2-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput2X",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v2-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput4X",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/netOutput1X",
            "Identity"
          ]
        },
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/netOutput2X",
            "Identity"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/netOutput4X",
            "Identity"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 1,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v2-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput1X",
            "tf.clip_by_value"
          ]
        },
        "2": {
          "nets": [
            "[N]-v2-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput2X",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v2-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput4X",
            "tf.clip_by_value"
          ]
        }
      }
    }
  },
  "cli": {
    "aliases": [
      "lines",
      "compression"
    ],
    "params": {
      "param1": "denoise",
      "param2": "sharpen"
    }
  }
}
```

</details>

### gffm.json

#### 基础信息

```json
{
  "name": "Face Mask",
  "shortName": "gffm",
  "category": "Face Recovery",
  "version": "1",
  "enabled": 3,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "netInput"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imn` | 0 | 1 | `"[N]-v[V]-fp32-[H]x[W]-ov.tz2"` | `[512,512]` | `"netOutput"` |
| onnx_qnn | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"` | `[512,512]` | `"netOutput"` |
| onnx | `imn` | 0 | 1 | `"[N]-v[V]-fp32-[H]x[W]-ox.tz2"` | `[512,512]` | `"netOutput"` |
| onnx16 | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev2-ort.tz2"` | `[512,512]` | `"netOutput"` |
| coreml | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev2-mlc.tz"` | `[512,512]` | `"netOutput"` |
| tensorrt | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev2-rt[C]-rt.tz2"` | `[512,512]` | `"netOutput"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "gffm",
  "name": "Face Mask",
  "category": "Face Recovery",
  "enabled": 3,
  "optional": 0,
  "padding": [
    0,
    0
  ],
  "inputs": {
    "input0": "netInput"
  },
  "backends": {
    "openvino": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev2-ort.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": 0,
      "minMacVersion": 10.16,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev2-mlc.tz"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev2-rt[C]-rt.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    }
  },
  "display": 0
}
```

</details>

### gfg.json

#### 基础信息

```json
{
  "name": "Face Perfect",
  "shortName": "gfg",
  "category": "Face Recovery",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "netInput"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imn` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-ov.tz2"` | `[512,512]` | `"netOutput"` |
| onnx_qnn | `imn` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"` | `[512,512]` | `"netOutput"` |
| onnx | `imn` | 1 | 1 | `"[N]-v[V]-fp32-[H]x[W]-ox.tz2"` | `[512,512]` | `"netOutput"` |
| coreml | `imn` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-mlc.tz"` | `[512,512]` | `"netOutput"` |
| tensorrt | `imn` | 0 | 1 | `"[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"` | `[512,512]` | `"netOutput"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "gfg",
  "name": "Face Perfect",
  "category": "Face Recovery",
  "verb": "Recovering faces",
  "enabled": 3,
  "optional": 1,
  "padding": [
    0,
    0
  ],
  "zeroCenter": 3,
  "inputs": {
    "input0": "netInput"
  },
  "backends": {
    "openvino": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": 1,
      "minMacVersion": 10.16,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-mlc.tz"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    }
  }
}
```

</details>

### gfp-l.json

#### 基础信息

```json
{
  "name": "Face Parse Large",
  "shortName": "gfp-l",
  "category": "Face Recovery",
  "version": "1",
  "enabled": 3,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "modelInput"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imn` | 0 | 1 | `"[N]-v[V]-fp32-[H]x[W]-ov.tz2"` | `[2048,2048]` | `"modelOutput"` |
| onnx_qnn | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"` | `[2048,2048]` | `"modelOutput"` |
| onnx | `imn` | 0 | 1 | `"[N]-v[V]-fp32-[H]x[W]-ox.tz2"` | `[2048,2048]` | `"modelOutput"` |
| coreml | `imn` | 0 | 1 | `"[N]-v[V]-fp32-[H]x[W]-mlc.tz"` | `[2048,2048]` | `"modelOutput"` |
| tensorrt | `imn` | 0 | 1 | `"[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"` | `[2048,2048]` | `"modelOutput"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "gfp-l",
  "name": "Face Parse Large",
  "category": "Face Recovery",
  "enabled": 3,
  "optional": 0,
  "padding": [
    0,
    0
  ],
  "inputs": {
    "input0": "modelInput"
  },
  "backends": {
    "openvino": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            2048,
            2048
          ],
          "outputs": [
            "modelOutput"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"
          ],
          "blocks": [
            2048,
            2048
          ],
          "outputs": [
            "modelOutput"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            2048,
            2048
          ],
          "outputs": [
            "modelOutput"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": 0,
      "minMacVersion": 10.16,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-mlc.tz"
          ],
          "blocks": [
            2048,
            2048
          ],
          "outputs": [
            "modelOutput"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            2048,
            2048
          ],
          "outputs": [
            "modelOutput"
          ]
        }
      }
    }
  },
  "display": 0
}
```

</details>

### gfp-s.json

#### 基础信息

```json
{
  "name": "Face Parse Small",
  "shortName": "gfp-s",
  "category": "Face Recovery",
  "version": "1",
  "enabled": 3,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "modelInput"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imn` | 1 | 1 | `"[N]-v[V]-fp32-[H]x[W]-ov.tz2"` | `[1024,1024]` | `"modelOutput"` |
| onnx_qnn | `imn` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"` | `[1024,1024]` | `"modelOutput"` |
| onnx | `imn` | 1 | 1 | `"[N]-v[V]-fp32-[H]x[W]-ox.tz2"` | `[1024,1024]` | `"modelOutput"` |
| coreml | `imn` | 1 | 1 | `"[N]-v[V]-fp32-[H]x[W]-mlc.tz"` | `[1024,1024]` | `"modelOutput"` |
| tensorrt | `imn` | 1 | 1 | `"[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"` | `[1024,1024]` | `"modelOutput"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "gfp-s",
  "name": "Face Parse Small",
  "category": "Face Recovery",
  "enabled": 3,
  "optional": 0,
  "padding": [
    0,
    0
  ],
  "inputs": {
    "input0": "modelInput"
  },
  "backends": {
    "openvino": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            1024,
            1024
          ],
          "outputs": [
            "modelOutput"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"
          ],
          "blocks": [
            1024,
            1024
          ],
          "outputs": [
            "modelOutput"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            1024,
            1024
          ],
          "outputs": [
            "modelOutput"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": 1,
      "minMacVersion": 10.16,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-mlc.tz"
          ],
          "blocks": [
            1024,
            1024
          ],
          "outputs": [
            "modelOutput"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 1,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            1024,
            1024
          ],
          "outputs": [
            "modelOutput"
          ]
        }
      }
    }
  },
  "display": 0
}
```

</details>

### gfpf.json

#### 基础信息

```json
{
  "name": "Face Parse Filtering",
  "shortName": "gfpf",
  "category": "Face Recovery",
  "version": "1",
  "enabled": 3,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "modelInput"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-ov.tz2"` | `[48,48]` | `"modelOutput"` |
| onnx_qnn | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"` | `[48,48]` | `"netOutput"` |
| onnx | `imn` | 0 | 1 | `"[N]-v[V]-fp32-[H]x[W]-ox.tz2"` | `[48,48]` | `"netOutput"` |
| coreml | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-mlc.tz"` | `[48,48]` | `"modelOutput"` |
| tensorrt | `imn` | 0 | 1 | `"[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"` | `[48,48]` | `"modelOutput"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "gfpf",
  "name": "Face Parse Filtering",
  "category": "Face Recovery",
  "enabled": 3,
  "optional": 0,
  "padding": [
    0,
    0
  ],
  "convertBGR": 3,
  "inputs": {
    "input0": "modelInput"
  },
  "backends": {
    "openvino": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            48,
            48
          ],
          "outputs": [
            "modelOutput"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"
          ],
          "blocks": [
            48,
            48
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            48,
            48
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-mlc.tz"
          ],
          "blocks": [
            48,
            48
          ],
          "outputs": [
            "modelOutput"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            48,
            48
          ],
          "outputs": [
            "modelOutput"
          ]
        }
      }
    }
  },
  "display": 0
}
```

</details>

### gfrf.json

#### 基础信息

```json
{
  "name": "Face Perfect fidelity",
  "shortName": "gfrf",
  "category": "Face Recovery",
  "version": "2",
  "enabled": 3,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "netInput"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imn` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-ov.tz2"` | `[1024,1024]` | `"netOutput"` |
| onnx | `imn` | 1 | 1 | `"[N]-v[V]-fp32-[H]x[W]-ox.tz2"` | `[1024,1024]` | `"netOutput"` |
| coreml | `imn` | 2 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev2-mlc.tz"` | `[1024,1024]` | `"netOutput"` |
| onnx16 | `imn` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev2-ort.tz2"` | `[1024,1024]` | `"netOutput"` |
| tensorrt | `imn` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev2-rt[C]-rt.tz2"` | `[1024,1024]` | `"netOutput"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "2",
  "minAppVersion": "0",
  "shortName": "gfrf",
  "name": "Face Perfect fidelity",
  "category": "Face Recovery",
  "verb": "Recovering faces",
  "enabled": 3,
  "optional": 0,
  "padding": [
    0,
    0
  ],
  "zeroCenter": 3,
  "inputs": {
    "input0": "netInput"
  },
  "backends": {
    "openvino": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            1024,
            1024
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            1024,
            1024
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": 2,
      "minMacVersion": 10.16,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev2-mlc.tz"
          ],
          "blocks": [
            1024,
            1024
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev2-ort.tz2"
          ],
          "blocks": [
            1024,
            1024
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 1,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev2-rt[C]-rt.tz2"
          ],
          "blocks": [
            1024,
            1024
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    }
  }
}
```

</details>

### gfrg.json

#### 基础信息

```json
{
  "name": "Face Perfect generative v3",
  "shortName": "gfrg",
  "category": "Face Recovery",
  "version": "3",
  "enabled": 3,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "netInput"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-ov.tz2"` | `[512,512]` | `"netOutput"` |
| onnx_qnn | `imn` | 0 | 1 | `"[N]-v[V]-fp32-[H]x[W]-ox.tz2"` | `[512,512]` | `"netOutput"` |
| onnx | `imn` | 0 | 1 | `"[N]-v[V]-fp32-[H]x[W]-ox.tz2"` | `[512,512]` | `"netOutput"` |
| coreml | `imn` | 0 | 1 | `"[N]-v[V]-fp32-[H]x[W]-rev1-mlc.tz"` | `[512,512]` | `"netOutput"` |
| tensorrt | `imn` | 0 | 1 | `"[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"` | `[512,512]` | `"netOutput"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "3",
  "minAppVersion": "0",
  "shortName": "gfrg",
  "name": "Face Perfect generative v3",
  "category": "Face Recovery",
  "verb": "Recovering faces",
  "enabled": 3,
  "optional": 0,
  "padding": [
    0,
    0
  ],
  "zeroCenter": 3,
  "inputs": {
    "input0": "netInput"
  },
  "backends": {
    "openvino": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": 0,
      "minMacVersion": 10.16,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 0,
      "capabilities": [
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput"
          ]
        }
      }
    }
  }
}
```

</details>

### ggi.json

#### 基础信息

```json
{
  "name": "CGI",
  "shortName": "ggi",
  "category": "Enhance",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": "gde_ap"
}
```

#### inputs 完整映射

```json
{
  "param1": "t_param",
  "param2": "t_param1",
  "input": "netInput",
  "cinput": "infer_input",
  "output": "infer_output",
  "gamma": "dummy"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["tl_unet1x2x4x/out2x/add_2","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["tl_unet1x2x4x/out4x/add_2","model/tf.clip_by_value/clip_by_value"]` |
| openvino16 | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["tl_unet1x2x4x/out2x/add_2","model/tf.clip_by_value/clip_by_value"]` |
| openvino16 | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["tl_unet1x2x4x/out4x/add_2","model/tf.clip_by_value/clip_by_value"]` |
| onnx | `imcc` | 1 | 2 | `["[N]-v2-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput2X","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 4 | `["[N]-v2-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput4X","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 2 | `["[N]-v2-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput2X","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 4 | `["[N]-v2-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput4X","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 2 | `["[N]-v2-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput2X","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 4 | `["[N]-v2-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput4X","tf.clip_by_value"]` |
| coreml | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[192,192]` | `["tl_unet1x2x4x/netOutput2X","Identity"]` |
| coreml | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[192,192]` | `["tl_unet1x2x4x/netOutput4X","Identity"]` |
| tensorrt | `imcc` | 0 | 2 | `["[N]-v2-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[192,192]` | `["netOutput2X","tf.clip_by_value"]` |
| tensorrt | `imcc` | 0 | 4 | `["[N]-v2-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[192,192]` | `["netOutput4X","tf.clip_by_value"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "uiVersion": "1",
  "minAppVersion": "0",
  "shortName": "ggi",
  "enabled": 3,
  "optional": 1,
  "name": "CGI",
  "category": "Enhance",
  "verb": "Enhancing",
  "autoModel": "gde_ap",
  "zeroCenter": 3,
  "inputs": {
    "param1": "t_param",
    "param2": "t_param1",
    "input": "netInput",
    "cinput": "infer_input",
    "output": "infer_output",
    "gamma": "dummy"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/out2x/add_2",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/out4x/add_2",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "openvino16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/out2x/add_2",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/out4x/add_2",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v2-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput2X",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v2-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput4X",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v2-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput2X",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v2-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput4X",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 1,
      "normalizeNames": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v2-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput2X",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v2-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput4X",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/netOutput2X",
            "Identity"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/netOutput4X",
            "Identity"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "2": {
          "nets": [
            "[N]-v2-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput2X",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v2-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput4X",
            "tf.clip_by_value"
          ]
        }
      }
    }
  },
  "cli": {
    "aliases": [
      "art",
      "cg",
      "cgi"
    ],
    "params": {
      "param1": "denoise",
      "param2": "sharpen"
    }
  }
}
```

</details>

### ggn_ap.json

#### 基础信息

```json
{
  "name": null,
  "shortName": "ggn_ap",
  "category": null,
  "version": "2",
  "enabled": 1,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "input"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imap` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev2-mlc.tz"` | `[128,128]` | `"output"` |
| openvino | `imap` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev2-ox.tz2"` | `[128,128]` | `"output"` |
| onnx | `imap` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev2-ox.tz2"` | `[128,128]` | `"output"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "2",
  "shortName": "ggn_ap",
  "enabled": 1,
  "optional": 0,
  "padding": [
    0,
    0
  ],
  "parameterNames": [
    "param2",
    "param1",
    "param3"
  ],
  "inputs": {
    "input": "input"
  },
  "backends": {
    "coreml": {
      "model": "imap",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev2-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "output"
          ]
        }
      }
    },
    "openvino": {
      "model": "imap",
      "parallel": 0,
      "transpose": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev2-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "output"
          ]
        }
      }
    },
    "onnx": {
      "model": "imap",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev2-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "output"
          ]
        }
      }
    }
  }
}
```

</details>

### ggn_noee.json

#### 基础信息

```json
{
  "name": "Standard noee",
  "shortName": "ggn_noee",
  "category": "Enhance",
  "version": "3",
  "enabled": 3,
  "optional": 1,
  "autoModel": "ggn_ap"
}
```

#### inputs 完整映射

```json
{
  "param1": "pn",
  "param2": "pb",
  "param3": "pc",
  "input": "netInput",
  "cinput": "infer_input",
  "output": "infer_output",
  "gamma": "dummy"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 1 | 2 | `["ggn-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[128,128]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 4 | `["ggn-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[128,128]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| coreml | `imcc` | -2 | 2 | `["ggn-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[128,128]` | `["netOutput","Identity"]` |
| coreml | `imcc` | -2 | 4 | `["ggn-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[128,128]` | `["netOutput","Identity"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "xParams": {
    "xIgnore": true
  },
  "jsonVersion": "1.0.0",
  "version": "3",
  "uiVersion": "1",
  "minAppVersion": "0",
  "shortName": "ggn_noee",
  "blockOverlap": 12,
  "blockDiscard": 2,
  "enabled": 3,
  "optional": 1,
  "name": "Standard noee",
  "category": "Enhance",
  "verb": "Enhancing",
  "autoModel": "ggn_ap",
  "inputs": {
    "param1": "pn",
    "param2": "pb",
    "param3": "pc",
    "input": "netInput",
    "cinput": "infer_input",
    "output": "infer_output",
    "gamma": "dummy"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "ggn-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "ggn-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": -2,
      "minMacVersion": 10.16,
      "scales": {
        "2": {
          "nets": [
            "ggn-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        },
        "4": {
          "nets": [
            "ggn-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    }
  },
  "cli": {
    "aliases": [
      "std",
      "standard"
    ],
    "params": {
      "param1": "denoise",
      "param2": "sharpen"
    }
  }
}
```

</details>

### ggn.json

#### 基础信息

```json
{
  "name": "Standard",
  "shortName": "ggn",
  "category": "Enhance",
  "version": "3",
  "enabled": 3,
  "optional": 1,
  "autoModel": "ggn_ap"
}
```

#### inputs 完整映射

```json
{
  "param1": "pn",
  "param2": "pb",
  "param3": "pc",
  "input": "netInput",
  "cinput": "infer_input",
  "output": "infer_output",
  "gamma": "dummy"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[128,128]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[128,128]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| onnx16 | `imcc` | 1 | 2 | `["[N]-v[V]-fix-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| coreml | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[128,128]` | `["netOutput","Identity"]` |
| coreml | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[128,128]` | `["netOutput","Identity"]` |
| tensorrt | `imcc` | 0 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| tensorrt | `imcc` | 0 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "3",
  "uiVersion": "1",
  "minAppVersion": "0",
  "shortName": "ggn",
  "blockOverlap": 12,
  "blockDiscard": 2,
  "enabled": 3,
  "optional": 1,
  "name": "Standard",
  "category": "Enhance",
  "verb": "Enhancing",
  "autoModel": "ggn_ap",
  "inputs": {
    "param1": "pn",
    "param2": "pb",
    "param3": "pc",
    "input": "netInput",
    "cinput": "infer_input",
    "output": "infer_output",
    "gamma": "dummy"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fix-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "minMacVersion": 10.16,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    }
  },
  "cli": {
    "aliases": [
      "std",
      "standard"
    ],
    "params": {
      "param1": "denoise",
      "param2": "sharpen"
    }
  }
}
```

</details>

### ggnv2.json

#### 基础信息

```json
{
  "name": "Standard V2",
  "shortName": "ggnv2",
  "category": "Enhance",
  "version": "3",
  "enabled": 3,
  "optional": 0,
  "autoModel": "ggn_ap"
}
```

#### inputs 完整映射

```json
{
  "param1": "pb",
  "param2": "pn",
  "param3": "pc",
  "input": "netInput",
  "cinput": "infer_input",
  "output": "infer_output",
  "gamma": "dummy"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-rev2-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[128,128]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-rev2-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[128,128]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| onnx16 | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| coreml | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[128,128]` | `["netOutput","Identity"]` |
| coreml | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[128,128]` | `["netOutput","Identity"]` |
| tensorrt | `imcc` | 0 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-revx-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| tensorrt | `imcc` | 0 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-revx-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "3",
  "uiVersion": "2",
  "minAppVersion": "0",
  "shortName": "ggnv2",
  "blockOverlap": 32,
  "blockDiscard": 4,
  "enabled": 3,
  "optional": 0,
  "name": "Standard V2",
  "category": "Enhance",
  "verb": "Enhancing",
  "autoModel": "ggn_ap",
  "inputs": {
    "param1": "pb",
    "param2": "pn",
    "param3": "pc",
    "input": "netInput",
    "cinput": "infer_input",
    "output": "infer_output",
    "gamma": "dummy"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-rev2-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-rev2-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "minMacVersion": 10.16,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 0,
      "capabilities": [
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-revx-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-revx-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    }
  },
  "cli": {
    "aliases": [
      "std",
      "standard"
    ],
    "params": {
      "param1": "denoise",
      "param2": "sharpen",
      "param3": "compression"
    }
  }
}
```

</details>

### ghc.json

#### 基础信息

```json
{
  "name": "High Compression",
  "shortName": "ghc",
  "category": "Enhance",
  "version": "2",
  "enabled": 1,
  "optional": 1,
  "autoModel": "ggn_ap"
}
```

#### inputs 完整映射

```json
{
  "param1": "param0",
  "param2": "param1",
  "input": "netInput",
  "cinput": "infer_input",
  "output": "infer_output",
  "gamma": "dummy"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 1 | 1 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["model_3/tf.__operators__.getitem_2/strided_slice","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["model_2/tf.__operators__.getitem_1/strided_slice","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["model_1/tf.__operators__.getitem/strided_slice","model/tf.clip_by_value/clip_by_value"]` |
| openvino16 | `imcc` | 1 | 1 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["model_3/tf.__operators__.getitem_2/strided_slice","model/tf.clip_by_value/clip_by_value"]` |
| openvino16 | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["model_2/tf.__operators__.getitem_1/strided_slice","model/tf.clip_by_value/clip_by_value"]` |
| openvino16 | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["model_1/tf.__operators__.getitem/strided_slice","model/tf.clip_by_value/clip_by_value"]` |
| onnx | `imcc` | 1 | 1 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["tf.identity_2","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["tf.identity_1","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["tf.identity","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 1 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["tf.identity_2","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["tf.identity_1","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["tf.identity","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 1 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["tf_identity_2","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["tf_identity_1","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["tf_identity","tf.clip_by_value"]` |
| coreml | `imcc` | 1 | 1 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp32-[H]x[W]-[S]x-mlc.tz"]` | `[192,192]` | `["Identity","Identity"]` |
| coreml | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp32-[H]x[W]-[S]x-mlc.tz"]` | `[192,192]` | `["Identity","Identity"]` |
| coreml | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp32-[H]x[W]-[S]x-mlc.tz"]` | `[192,192]` | `["Identity","Identity"]` |
| tensorrt | `imcc` | 1 | 1 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[192,192]` | `["tf.identity_2","tf.clip_by_value"]` |
| tensorrt | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[192,192]` | `["tf.identity_1","tf.clip_by_value"]` |
| tensorrt | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[192,192]` | `["tf.identity","tf.clip_by_value"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "2",
  "uiVersion": "1",
  "minAppVersion": "5.5.0",
  "shortName": "ghc",
  "enabled": 1,
  "optional": 1,
  "name": "High Compression",
  "category": "Enhance",
  "verb": "Enhancing",
  "autoModel": "ggn_ap",
  "zeroCenter": 3,
  "inputs": {
    "param1": "param0",
    "param2": "param1",
    "input": "netInput",
    "cinput": "infer_input",
    "output": "infer_output",
    "gamma": "dummy"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "model_3/tf.__operators__.getitem_2/strided_slice",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "model_2/tf.__operators__.getitem_1/strided_slice",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "model_1/tf.__operators__.getitem/strided_slice",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "openvino16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "model_3/tf.__operators__.getitem_2/strided_slice",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "model_2/tf.__operators__.getitem_1/strided_slice",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "model_1/tf.__operators__.getitem/strided_slice",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tf.identity_2",
            "tf.clip_by_value"
          ]
        },
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tf.identity_1",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tf.identity",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tf.identity_2",
            "tf.clip_by_value"
          ]
        },
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tf.identity_1",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tf.identity",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tf_identity_2",
            "tf.clip_by_value"
          ]
        },
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tf_identity_1",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tf_identity",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp32-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "Identity",
            "Identity"
          ]
        },
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp32-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "Identity",
            "Identity"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp32-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "Identity",
            "Identity"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 1,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tf.identity_2",
            "tf.clip_by_value"
          ]
        },
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tf.identity_1",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tf.identity",
            "tf.clip_by_value"
          ]
        }
      }
    }
  },
  "cli": {
    "aliases": [
      "very compressed",
      "high compression",
      "vc"
    ],
    "params": {
      "param1": "denoise",
      "param2": "sharpen"
    }
  }
}
```

</details>

### ghq_noee.json

#### 基础信息

```json
{
  "name": "High Fidelity noee",
  "shortName": "ghq_noee",
  "category": "Enhance",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": "ggn_ap"
}
```

#### inputs 完整映射

```json
{
  "param1": "pn",
  "param2": "pb",
  "param3": "pc",
  "input": "netInput",
  "cinput": "infer_input",
  "output": "infer_output",
  "gamma": "dummy"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 1 | 2 | `["ghq-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[96,96]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 4 | `["ghq-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[96,96]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| coreml | `imcc` | -1 | 2 | `["ghq-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[96,96]` | `["netOutput","Identity"]` |
| coreml | `imcc` | -1 | 4 | `["ghq-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[96,96]` | `["netOutput","Identity"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "xParams": {
    "xIgnore": true
  },
  "jsonVersion": "1.0.0",
  "version": "1",
  "uiVersion": "1",
  "minAppVersion": "0",
  "shortName": "ghq_noee",
  "blockOverlap": 12,
  "blockDiscard": 2,
  "enabled": 3,
  "optional": 1,
  "name": "High Fidelity noee",
  "category": "Enhance",
  "verb": "Enhancing",
  "autoModel": "ggn_ap",
  "inputs": {
    "param1": "pn",
    "param2": "pb",
    "param3": "pc",
    "input": "netInput",
    "cinput": "infer_input",
    "output": "infer_output",
    "gamma": "dummy"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "ghq-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "ghq-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": -1,
      "minMacVersion": 10.16,
      "scales": {
        "2": {
          "nets": [
            "ghq-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        },
        "4": {
          "nets": [
            "ghq-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    }
  },
  "cli": {
    "aliases": [
      "hf",
      "high fidelity",
      "fidelity"
    ],
    "params": {
      "param1": "denoise",
      "param2": "sharpen"
    }
  }
}
```

</details>

### ghq.json

#### 基础信息

```json
{
  "name": "High Fidelity",
  "shortName": "ghq",
  "category": "Enhance",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": "ggn_ap"
}
```

#### inputs 完整映射

```json
{
  "param1": "pn",
  "param2": "pb",
  "param3": "pc",
  "input": "netInput",
  "cinput": "infer_input",
  "output": "infer_output",
  "gamma": "dummy"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[96,96]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[96,96]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| onnx16 | `imcc` | 1 | 2 | `["[N]-v[V]-fix-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[96,96]` | `["netOutput","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[96,96]` | `["netOutput","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[96,96]` | `["netOutput","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[96,96]` | `["netOutput","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[96,96]` | `["netOutput","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[96,96]` | `["netOutput","tf.clip_by_value"]` |
| coreml | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[96,96]` | `["netOutput","Identity"]` |
| coreml | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[96,96]` | `["netOutput","Identity"]` |
| tensorrt | `imcc` | 0 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[96,96]` | `["netOutput","tf.clip_by_value"]` |
| tensorrt | `imcc` | 0 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[96,96]` | `["netOutput","tf.clip_by_value"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "uiVersion": "1",
  "minAppVersion": "0",
  "shortName": "ghq",
  "blockOverlap": 12,
  "blockDiscard": 2,
  "enabled": 3,
  "optional": 1,
  "name": "High Fidelity",
  "category": "Enhance",
  "verb": "Enhancing",
  "autoModel": "ggn_ap",
  "inputs": {
    "param1": "pn",
    "param2": "pb",
    "param3": "pc",
    "input": "netInput",
    "cinput": "infer_input",
    "output": "infer_output",
    "gamma": "dummy"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fix-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "minMacVersion": 10.16,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    }
  },
  "cli": {
    "aliases": [
      "hf",
      "high fidelity",
      "fidelity"
    ],
    "params": {
      "param1": "denoise",
      "param2": "sharpen"
    }
  }
}
```

</details>

### ghqv2_ldn.json

#### 基础信息

```json
{
  "name": "High Fidelity V2 LDN",
  "shortName": "ghqv2_ldn",
  "category": "Enhance",
  "version": "1",
  "enabled": 3,
  "optional": 0,
  "autoModel": "ggn_ap"
}
```

#### inputs 完整映射

```json
{
  "param1": "pb",
  "param2": "pn",
  "param3": "pc",
  "input": "netInput",
  "cinput": "infer_input",
  "output": "infer_output",
  "gamma": "dummy"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-rev2-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[128,128]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-rev2-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[128,128]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| onnx16 | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| coreml | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[128,128]` | `["netOutput","Identity"]` |
| coreml | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[128,128]` | `["netOutput","Identity"]` |
| tensorrt | `imcc` | 0 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| tensorrt | `imcc` | 0 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "ghqv2_ldn",
  "blockOverlap": 70,
  "blockDiscard": 6,
  "enabled": 3,
  "optional": 0,
  "name": "High Fidelity V2 LDN",
  "category": "Enhance",
  "verb": "Enhancing",
  "autoModel": "ggn_ap",
  "inputs": {
    "param1": "pb",
    "param2": "pn",
    "param3": "pc",
    "input": "netInput",
    "cinput": "infer_input",
    "output": "infer_output",
    "gamma": "dummy"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-rev2-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-rev2-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "minMacVersion": 10.16,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    }
  }
}
```

</details>

### ghqv2.json

#### 基础信息

```json
{
  "name": "High Fidelity V2",
  "shortName": "ghqv2",
  "category": "Enhance",
  "version": "1",
  "enabled": 3,
  "optional": 0,
  "autoModel": "ggn_ap"
}
```

#### inputs 完整映射

```json
{
  "param1": "pb",
  "param2": "pn",
  "param3": "pc",
  "input": "netInput",
  "cinput": "infer_input",
  "output": "infer_output",
  "gamma": "dummy"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-rev2-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[128,128]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-rev2-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[128,128]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| onnx16 | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| coreml | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[128,128]` | `["netOutput","Identity"]` |
| coreml | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[128,128]` | `["netOutput","Identity"]` |
| tensorrt | `imcc` | 0 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| tensorrt | `imcc` | 0 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "uiVersion": "2",
  "minAppVersion": "0",
  "shortName": "ghqv2",
  "blockOverlap": 70,
  "blockDiscard": 6,
  "enabled": 3,
  "optional": 0,
  "name": "High Fidelity V2",
  "category": "Enhance",
  "verb": "Enhancing",
  "autoModel": "ggn_ap",
  "inputs": {
    "param1": "pb",
    "param2": "pn",
    "param3": "pc",
    "input": "netInput",
    "cinput": "infer_input",
    "output": "infer_output",
    "gamma": "dummy"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-rev2-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-rev2-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "minMacVersion": 10.16,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    }
  },
  "cli": {
    "aliases": [
      "hf",
      "high fidelity",
      "fidelity"
    ],
    "params": {
      "param1": "denoise",
      "param2": "sharpen",
      "param3": "compression"
    }
  }
}
```

</details>

### ghqv3_cache.json

#### 基础信息

```json
{
  "name": "High Fidelity V3 Cache",
  "shortName": "ghqv3_cache",
  "category": "Enhance",
  "version": "2",
  "enabled": 3,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "image",
  "strength": "recovery",
  "upscale": "upscale"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-ox.tz2"` | `[224,224]` | `"cond"` |
| onnx | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-ox.tz2"` | `[224,224]` | `"cond"` |
| coreml | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-mlc.tz"` | `[224,224]` | `"cond"` |
| tensorrt | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2"` | `[224,224]` | `"cond"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "2",
  "shortName": "ghqv3_cache",
  "enabled": 3,
  "optional": 0,
  "name": "High Fidelity V3 Cache",
  "category": "Enhance",
  "verb": "Enhancing",
  "inputs": {
    "input0": "image",
    "strength": "recovery",
    "upscale": "upscale"
  },
  "backends": {
    "openvino": {
      "model": "imn",
      "parallel": 0,
      "transpose": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            224,
            224
          ],
          "outputs": [
            "cond"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            224,
            224
          ],
          "outputs": [
            "cond"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": 0,
      "minMacVersion": 10.16,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-mlc.tz"
          ],
          "blocks": [
            224,
            224
          ],
          "outputs": [
            "cond"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            224,
            224
          ],
          "outputs": [
            "cond"
          ]
        }
      }
    }
  }
}
```

</details>

### ghqv3.json

#### 基础信息

```json
{
  "name": "High Fidelity V3",
  "shortName": "ghqv3",
  "category": "Enhance",
  "version": "2",
  "enabled": 3,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "tile",
  "input1": "cond"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imn` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev1-ox.tz2"` | `[512,512]` | `"output"` |
| onnx | `imn` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev1-ort.tz2"` | `[512,512]` | `"output"` |
| coreml | `imn` | -1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz"` | `[512,512]` | `"output"` |
| tensorrt | `imn` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev1-rt[C]-rt.tz2"` | `[512,512]` | `"output"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "2",
  "shortName": "ghqv3",
  "blockOverlap": 96,
  "blockDiscard": 8,
  "enabled": 3,
  "optional": 0,
  "name": "High Fidelity V3",
  "category": "Enhance",
  "verb": "Enhancing",
  "inputs": {
    "input0": "tile",
    "input1": "cond"
  },
  "backends": {
    "openvino": {
      "model": "imn",
      "parallel": 1,
      "transpose": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "output"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-ort.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "output"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": -1,
      "minMacVersion": 10.16,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "output"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 1,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-rt[C]-rt.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "output"
          ]
        }
      }
    }
  }
}
```

</details>

### gmp.json

#### 基础信息

```json
{
  "name": "Low Resolution",
  "shortName": "gmp",
  "category": "Enhance",
  "version": "1",
  "enabled": 3,
  "optional": 0,
  "autoModel": "ggn_ap"
}
```

#### inputs 完整映射

```json
{
  "param1": "t_param",
  "param2": "t_param1",
  "input": "netInput",
  "cinput": "infer_input",
  "output": "infer_output",
  "gamma": "dummy"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["tl_unet1x2x4x/out2x/add_2","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["tl_unet1x2x4x/out4x/add_2","model/tf.clip_by_value/clip_by_value"]` |
| openvino16 | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["tl_unet1x2x4x/out2x/add_2","model/tf.clip_by_value/clip_by_value"]` |
| openvino16 | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["tl_unet1x2x4x/out4x/add_2","model/tf.clip_by_value/clip_by_value"]` |
| onnx | `imcc` | 1 | 2 | `["[N]-v2-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput2X","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 4 | `["[N]-v2-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput4X","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 2 | `["[N]-v2-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput2X_0","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 4 | `["[N]-v2-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput4X_0","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 2 | `["[N]-v2-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput2X","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 4 | `["[N]-v2-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput4X","tf.clip_by_value"]` |
| coreml | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[192,192]` | `["tl_unet1x2x4x/netOutput2X","Identity"]` |
| coreml | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[192,192]` | `["tl_unet1x2x4x/netOutput4X","Identity"]` |
| tensorrt | `imcc` | 0 | 2 | `["[N]-v2-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[192,192]` | `["netOutput2X","tf.clip_by_value"]` |
| tensorrt | `imcc` | 0 | 4 | `["[N]-v2-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[192,192]` | `["netOutput4X","tf.clip_by_value"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "uiVersion": "1",
  "minAppVersion": "0",
  "shortName": "gmp",
  "enabled": 3,
  "optional": 0,
  "name": "Low Resolution",
  "category": "Enhance",
  "verb": "Enhancing",
  "autoModel": "ggn_ap",
  "zeroCenter": 3,
  "inputs": {
    "param1": "t_param",
    "param2": "t_param1",
    "input": "netInput",
    "cinput": "infer_input",
    "output": "infer_output",
    "gamma": "dummy"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/out2x/add_2",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/out4x/add_2",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "openvino16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/out2x/add_2",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/out4x/add_2",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v2-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput2X",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v2-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput4X",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 1,
      "normalizeNames": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v2-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput2X_0",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v2-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput4X_0",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v2-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput2X",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v2-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput4X",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/netOutput2X",
            "Identity"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "tl_unet1x2x4x/netOutput4X",
            "Identity"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "2": {
          "nets": [
            "[N]-v2-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput2X",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v2-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput4X",
            "tf.clip_by_value"
          ]
        }
      }
    }
  },
  "cli": {
    "aliases": [
      "low",
      "lowres",
      "low resolution",
      "low res"
    ],
    "params": {
      "param1": "denoise",
      "param2": "sharpen"
    }
  }
}
```

</details>

### gmpv2.json

#### 基础信息

```json
{
  "name": "Low Resolution V2",
  "shortName": "gmpv2",
  "category": "Enhance",
  "version": "13",
  "enabled": 1,
  "optional": 1,
  "autoModel": "ggn_ap"
}
```

#### inputs 完整映射

```json
{
  "param1": "pb",
  "param2": "pn",
  "param3": "pc",
  "input": "netInput",
  "cinput": "infer_input",
  "output": "infer_output",
  "gamma": "dummy"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[192,192]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| onnx16 | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[192,192]` | `["netOutput","tf.clip_by_value"]` |
| coreml | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[192,192]` | `["netOutput","Identity"]` |
| coreml | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[192,192]` | `["netOutput","Identity"]` |
| tensorrt | `imcc` | 0 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[192,192]` | `["netOutput","tf.clip_by_value"]` |
| tensorrt | `imcc` | 0 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[192,192]` | `["netOutput","tf.clip_by_value"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "13",
  "uiVersion": "2",
  "minAppVersion": "0",
  "shortName": "gmpv2",
  "blockOverlap": 48,
  "blockDiscard": 10,
  "enabled": 1,
  "optional": 1,
  "name": "Low Resolution V2",
  "category": "Enhance",
  "verb": "Enhancing",
  "autoModel": "ggn_ap",
  "inputs": {
    "param1": "pb",
    "param2": "pn",
    "param3": "pc",
    "input": "netInput",
    "cinput": "infer_input",
    "output": "infer_output",
    "gamma": "dummy"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "minMacVersion": 10.16,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    }
  },
  "cli": {
    "aliases": [
      "low",
      "lowres",
      "low resolution",
      "low res"
    ],
    "params": {
      "param1": "denoise",
      "param2": "sharpen",
      "param3": "compression"
    }
  }
}
```

</details>

### irwn_dec.json

#### 基础信息

```json
{
  "name": "irwn_dec",
  "shortName": "irwn_dec",
  "category": "Enhance",
  "version": "2",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "latent_sample"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | -1 | 8 | `"[N]-v[V]-fp16-[H]x[W]-mlc.tz"` | `[64,64]` | `"sample"` |
| onnx16 | `imn` | 0 | 8 | `["[N]-v[V]-fp32-[H]x[W]-ox.tz2","[N]-v[V]-fp32-[H]x[W].onnx.data"]` | `[64,64]` | `"sample"` |
| openvino16 | `imn` | 0 | 8 | `["[N]-v[V]-fp32-[H]x[W]-ox.tz2","[N]-v[V]-fp32-[H]x[W].onnx.data"]` | `[64,64]` | `"sample"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "xParams": {
    "xIgnore": true
  },
  "jsonVersion": "1.0.0",
  "version": "2",
  "minAppVersion": "0",
  "shortName": "irwn_dec",
  "name": "irwn_dec",
  "category": "Enhance",
  "enabled": 3,
  "optional": 1,
  "zeroCenter": 2,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 16,
  "blockDiscard": 0,
  "inputs": {
    "input": "latent_sample"
  },
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": -1,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 320,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-mlc.tz"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imn",
      "parallel": 0,
      "external": 1,
      "blockProcTime": 90,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2",
            "[N]-v[V]-fp32-[H]x[W].onnx.data"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample"
          ]
        }
      }
    },
    "openvino16": {
      "model": "imn",
      "parallel": 0,
      "transpose": 0,
      "blockProcTime": 580,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2",
            "[N]-v[V]-fp32-[H]x[W].onnx.data"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample"
          ]
        }
      }
    }
  }
}
```

</details>

### irwn_dit.json

#### 基础信息

```json
{
  "name": "irwn_dit",
  "shortName": "irwn_dit",
  "category": "Enhance",
  "version": "2",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "sample"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | -1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-mlc.tz"` | `[128,128]` | `"out_sample"` |
| onnx | `imn` | 0 | 1 | `["[N]-v[V]-fp16-[H]x[W]-ox.tz2","[N]-v[V]-fp16-[H]x[W].onnx.data"]` | `[128,128]` | `"out_sample"` |
| onnx16 | `imn` | 0 | 1 | `["[N]-v[V]-fp16-[H]x[W]-rev1-ox.tz2","[N]-v[V]-fp16-[H]x[W]-rev1.onnx.data"]` | `[128,128]` | `"out_sample"` |
| openvino16 | `imn` | 0 | 1 | `["[N]-v[V]-fp32-[H]x[W]-ox.tz2","[N]-v[V]-fp32-[H]x[W].onnx.data"]` | `[128,128]` | `"out_sample"` |
| tensorrt | `imn` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2"` | `[128,128]` | `"out_sample"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "xParams": {
    "xIgnore": true
  },
  "jsonVersion": "1.0.0",
  "version": "2",
  "minAppVersion": "0",
  "shortName": "irwn_dit",
  "name": "irwn_dit",
  "category": "Enhance",
  "enabled": 3,
  "optional": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 64,
  "blockDiscard": 0,
  "inputs": {
    "input": "sample"
  },
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": -1,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 480,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "out_sample"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 0,
      "external": 1,
      "blockProcTime": 160,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2",
            "[N]-v[V]-fp16-[H]x[W].onnx.data"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "out_sample"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imn",
      "parallel": 0,
      "external": 1,
      "blockProcTime": 160,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-ox.tz2",
            "[N]-v[V]-fp16-[H]x[W]-rev1.onnx.data"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "out_sample"
          ]
        }
      }
    },
    "openvino16": {
      "model": "imn",
      "parallel": 0,
      "transpose": 0,
      "blockProcTime": 600,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2",
            "[N]-v[V]-fp32-[H]x[W].onnx.data"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "out_sample"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 1,
      "blockProcTime": 160,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "out_sample"
          ]
        }
      }
    }
  }
}
```

</details>

### irwn_enc.json

#### 基础信息

```json
{
  "name": "irwn_enc",
  "shortName": "irwn_enc",
  "category": "Enhance",
  "version": "2",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "sample"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | -1 | 0.125 | `"[N]-v[V]-fp16-[H]x[W]-mlc.tz"` | `[512,512]` | `"latent_sample"` |
| onnx16 | `imn` | 0 | 0.125 | `["[N]-v[V]-fp32-[H]x[W]-ox.tz2","[N]-v[V]-fp32-[H]x[W].onnx.data"]` | `[512,512]` | `"latent_sample"` |
| openvino16 | `imn` | 0 | 0.125 | `["[N]-v[V]-fp32-[H]x[W]-ox.tz2","[N]-v[V]-fp32-[H]x[W].onnx.data"]` | `[512,512]` | `"latent_sample"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "xParams": {
    "xIgnore": true
  },
  "jsonVersion": "1.0.0",
  "version": "2",
  "minAppVersion": "0",
  "shortName": "irwn_enc",
  "name": "irwn_enc",
  "category": "Enhance",
  "enabled": 3,
  "optional": 1,
  "zeroCenter": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 128,
  "blockDiscard": 0,
  "inputs": {
    "input": "sample"
  },
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": -1,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 200,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-mlc.tz"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imn",
      "parallel": 0,
      "external": 1,
      "blockProcTime": 90,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2",
            "[N]-v[V]-fp32-[H]x[W].onnx.data"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "openvino16": {
      "model": "imn",
      "parallel": 0,
      "transpose": 0,
      "blockProcTime": 420,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2",
            "[N]-v[V]-fp32-[H]x[W].onnx.data"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    }
  }
}
```

</details>

### ldd21.json

#### 基础信息

```json
{
  "name": "RescueD",
  "shortName": "ldd21",
  "category": "Enhance",
  "version": "2",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "latent_sample",
  "cinput": "netRef",
  "output": "netInput"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 0 | 8 | `["[N]-v[V]-fp16-[H]x[W]-ov.tz2","ldclc-v1-fp16-[H]x[W]-ov.tz2"]` | `[64,64]` | `["sample","netOutput"]` |
| onnx16 | `imcc` | 0 | 8 | `["[N]-v[V]-fp16-[H]x[W]-ox.tz2","ldclc-v1-fp16-[H]x[W]-ox.tz2"]` | `[64,64]` | `["sample","netOutput"]` |
| onnx | `imcc` | 0 | 8 | `["[N]-v[V]-fp32-[H]x[W]-ox.tz2","ldclc-v1-fp32-[H]x[W]-ox.tz2"]` | `[64,64]` | `["sample","netOutput"]` |
| onnx_qnn | `imcc` | 0 | 8 | `["[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2","ldclc-v1-fp16-[H]x[W]-qnn-ox.tz2"]` | `[64,64]` | `["sample","netOutput"]` |
| tensorrt | `imcc` | 0 | 8 | `["[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2","ldclc-v1-fp32-[H]x[W]-rt[C]-rt.tz2"]` | `[64,64]` | `["sample","netOutput"]` |
| coreml | `imcc` | 0 | 8 | `["[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz","ldclc-v1-fp16-[H]x[W]-rev1-mlc.tz"]` | `[64,64]` | `["sample","netOutput"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "2",
  "minAppVersion": "0",
  "shortName": "ldd21",
  "name": "RescueD",
  "category": "Enhance",
  "verb": "Enhancing",
  "enabled": 1,
  "optional": 1,
  "zeroCenter": 2,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 24,
  "blockDiscard": 6,
  "inputs": {
    "input": "latent_sample",
    "cinput": "netRef",
    "output": "netInput"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 4,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ov.tz2",
            "ldclc-v1-fp16-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 9,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2",
            "ldclc-v1-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 28,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2",
            "ldclc-v1-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 28,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2",
            "ldclc-v1-fp16-[H]x[W]-qnn-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2",
            "ldclc-v1-fp32-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 0,
      "minMacVersion": 13,
      "supportsIntel": 0,
      "blockProcTime": 16,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz",
            "ldclc-v1-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    }
  }
}
```

</details>

### lddv21_noclc.json

#### 基础信息

```json
{
  "name": "RescueDV_NOCLC",
  "shortName": "lddv21_noclc",
  "category": "Enhance",
  "version": "1",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "latent_sample"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imn` | 0 | 8 | `"lddv21-v[V]-fp16-[H]x[W]-ov.tz2"` | `[64,64]` | `"sample"` |
| onnx16 | `imn` | 0 | 8 | `"lddv21-v[V]-fp16-[H]x[W]-ox.tz2"` | `[64,64]` | `"sample"` |
| onnx | `imn` | 0 | 8 | `"lddv21-v[V]-fp32-[H]x[W]-ox.tz2"` | `[64,64]` | `"sample"` |
| onnx_qnn | `imn` | 0 | 8 | `"lddv21-v[V]-fp16-[H]x[W]-qnn-ox.tz2"` | `[64,64]` | `"sample"` |
| tensorrt | `imn` | 0 | 8 | `"lddv21-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"` | `[64,64]` | `"sample"` |
| coreml | `imn` | 0 | 8 | `"lddv21-v[V]-fp16-[H]x[W]-rev1-mlc.tz"` | `[64,64]` | `"sample"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "lddv21_noclc",
  "name": "RescueDV_NOCLC",
  "category": "Enhance",
  "verb": "Enhancing",
  "enabled": 1,
  "optional": 1,
  "zeroCenter": 2,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 24,
  "blockDiscard": 6,
  "inputs": {
    "input": "latent_sample"
  },
  "backends": {
    "openvino": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "8": {
          "nets": [
            "lddv21-v[V]-fp16-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "8": {
          "nets": [
            "lddv21-v[V]-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "8": {
          "nets": [
            "lddv21-v[V]-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imn",
      "parallel": 0,
      "scales": {
        "8": {
          "nets": [
            "lddv21-v[V]-fp16-[H]x[W]-qnn-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "8": {
          "nets": [
            "lddv21-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": 0,
      "minMacVersion": 13,
      "supportsIntel": 0,
      "scales": {
        "8": {
          "nets": [
            "lddv21-v[V]-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample"
          ]
        }
      }
    }
  }
}
```

</details>

### lddv21.json

#### 基础信息

```json
{
  "name": "RescueDV",
  "shortName": "lddv21",
  "category": "Enhance",
  "version": "1",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "latent_sample",
  "cinput": "netRef",
  "output": "netInput"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 0 | 8 | `["[N]-v[V]-fp16-[H]x[W]-ov.tz2","ldclc-v1-fp16-[H]x[W]-ov.tz2"]` | `[64,64]` | `["sample","netOutput"]` |
| onnx16 | `imcc` | 0 | 8 | `["[N]-v[V]-fp16-[H]x[W]-ox.tz2","ldclc-v1-fp16-[H]x[W]-ox.tz2"]` | `[64,64]` | `["sample","netOutput"]` |
| onnx | `imcc` | 0 | 8 | `["[N]-v[V]-fp32-[H]x[W]-ox.tz2","ldclc-v1-fp32-[H]x[W]-ox.tz2"]` | `[64,64]` | `["sample","netOutput"]` |
| onnx_qnn | `imcc` | 0 | 8 | `["[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2","ldclc-v1-fp16-[H]x[W]-qnn-ox.tz2"]` | `[64,64]` | `["sample","netOutput"]` |
| tensorrt | `imcc` | 0 | 8 | `["[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2","ldclc-v1-fp32-[H]x[W]-rt[C]-rt.tz2"]` | `[64,64]` | `["sample","netOutput"]` |
| coreml | `imcc` | 0 | 8 | `["[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz","ldclc-v1-fp16-[H]x[W]-rev1-mlc.tz"]` | `[64,64]` | `["sample","netOutput"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "lddv21",
  "name": "RescueDV",
  "category": "Enhance",
  "verb": "Enhancing",
  "enabled": 1,
  "optional": 1,
  "zeroCenter": 2,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 24,
  "blockDiscard": 6,
  "inputs": {
    "input": "latent_sample",
    "cinput": "netRef",
    "output": "netInput"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 4,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ov.tz2",
            "ldclc-v1-fp16-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 9,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2",
            "ldclc-v1-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 28,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2",
            "ldclc-v1-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 28,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2",
            "ldclc-v1-fp16-[H]x[W]-qnn-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2",
            "ldclc-v1-fp32-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 0,
      "minMacVersion": 13,
      "supportsIntel": 0,
      "blockProcTime": 16,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz",
            "ldclc-v1-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    }
  }
}
```

</details>

### lde21.json

#### 基础信息

```json
{
  "name": "RescueE",
  "shortName": "lde21",
  "category": "Enhance",
  "version": "1",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "sample"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imn` | 0 | 0.125 | `"[N]-v[V]-fp16-[H]x[W]-ov.tz2"` | `[512,512]` | `"latent_sample"` |
| onnx16 | `imn` | 0 | 0.125 | `"[N]-v[V]-fp16-[H]x[W]-ox.tz2"` | `[512,512]` | `"latent_sample"` |
| onnx | `imn` | 0 | 0.125 | `"[N]-v[V]-fp32-[H]x[W]-ox.tz2"` | `[512,512]` | `"latent_sample"` |
| onnx_qnn | `imn` | 0 | 0.125 | `"[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"` | `[512,512]` | `"latent_sample"` |
| tensorrt | `imn` | 0 | 0.125 | `"[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"` | `[512,512]` | `"latent_sample"` |
| coreml | `imn` | 0 | 0.125 | `"[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz"` | `[512,512]` | `"latent_sample"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "lde21",
  "name": "RescueE",
  "category": "Enhance",
  "verb": "Enhancing",
  "enabled": 1,
  "optional": 1,
  "zeroCenter": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 160,
  "blockDiscard": 40,
  "inputs": {
    "input0": "sample"
  },
  "backends": {
    "openvino": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 2,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 5,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 14,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 14,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": 0,
      "minMacVersion": 13,
      "supportsIntel": 0,
      "blockProcTime": 8,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    }
  }
}
```

</details>

### ldu21.json

#### 基础信息

```json
{
  "name": "RescueU",
  "shortName": "ldu21",
  "category": "Enhance",
  "version": "2",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "sample",
  "input1": "latent",
  "timestep": "timestep"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-ov.tz2"` | `[64,64]` | `"m/out_sample"` |
| onnx | `imn` | 0 | 1 | `["[N]-v[V]-fp32-[H]x[W]-rev1-ox.tz2","[N]-v[V]-fp32-[H]x[W]-rev1.pb"]` | `[64,64]` | `"m/out_sample"` |
| onnx16 | `imn` | 0 | 1 | `["[N]-amd-v[V]-fp16-[H]x[W]-ox.tz2","[N]-amd-v[V]-fp16-[H]x[W].pb"]` | `[64,64]` | `"m/out_sample"` |
| tensorrt | `imn` | 0 | 1 | `"[N]-v[V]-fp32-[H]x[W]-rev1-rt[C]-rt.tz2"` | `[64,64]` | `"out_sample"` |
| coreml | `imn` | -1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz"` | `[64,64]` | `"noise_pred"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "2",
  "minAppVersion": "0",
  "shortName": "ldu21",
  "name": "RescueU",
  "category": "Enhance",
  "verb": "Enhancing",
  "enabled": 1,
  "optional": 1,
  "blockOverlap": 32,
  "blockDiscard": 0,
  "blockPadExact": 0,
  "padding": [
    0,
    0
  ],
  "inputs": {
    "input0": "sample",
    "input1": "latent",
    "timestep": "timestep"
  },
  "backends": {
    "openvino": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 2,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "m/out_sample"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 0,
      "external": 1,
      "blockProcTime": 5,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rev1-ox.tz2",
            "[N]-v[V]-fp32-[H]x[W]-rev1.pb"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "m/out_sample"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imn",
      "parallel": 0,
      "external": 1,
      "blockProcTime": 5,
      "scales": {
        "1": {
          "nets": [
            "[N]-amd-v[V]-fp16-[H]x[W]-ox.tz2",
            "[N]-amd-v[V]-fp16-[H]x[W].pb"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "m/out_sample"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 0,
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rev1-rt[C]-rt.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "out_sample"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": -1,
      "minMacVersion": 13,
      "supportsIntel": 0,
      "blockProcTime": 10,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "noise_pred"
          ]
        }
      }
    }
  }
}
```

</details>

### neuroserver.json

#### 基础信息

```json
{
  "name": null,
  "shortName": null,
  "category": null,
  "version": "20260728.0",
  "enabled": 3,
  "optional": null,
  "autoModel": null
}
```

#### inputs 完整映射

```json
null
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| _NONE_ | `null` | null | null | `null` | `null` | `null` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "version": "20260728.0",
  "enabled": 3,
  "validate_install": {
    "windows": {
      "neuroserver-deps.tar.xz": "434384a7630120d6de50e5ead76751196525519379b7d02b1271e850d11bb08228d5b34eb120bd56303815480cef6a85709418bbccbcac884a656b43ce8197df",
      "neuroserver.tar.xz": "ecfc3a419b27accf54ba7e5719902582140f155923a0f712821ca8e4662bb463868be38fde3c0db4dc790a2b6280dc0000963e3429daf916d8da237391f1028d"
    },
    "mac": {
      "neuroserver-deps.tar.xz": "82188954977390235335d8a36e6ed02fbb117cb98bcc716800c242a0c422bdac87e4843baeca59fef7c55ffce5c4b41d9a22603a6d89bafc26348a0bd50b361c",
      "neuroserver.tar.xz": "98ba9ef6310af358d773ef86c5d8983d22630fd3dcb1e8c7fb8eaaf380821fc8605741d6df8c5ec775e535d745e33c09069c2018823c563814523d28dd62b746"
    }
  },
  "models": [
    "wonder-2",
    "wonder-all"
  ]
}
```

</details>

### rxl_decoder0.json

#### 基础信息

```json
{
  "name": "RecoveryXLD0",
  "shortName": "rxl_decoder0",
  "category": "Enhance",
  "version": "1",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "latent_sample",
  "cinput": "netRef",
  "output": "netInput"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| onnx16 | `imcc` | 0 | 8 | `["[N]-v[V]-fp16-[H]x[W]-ox.tz2","ldclc-v1-fp16-[H]x[W]-ox.tz2"]` | `[96,96]` | `["sample","netOutput"]` |
| onnx | `imcc` | 0 | 8 | `["[N]-v[V]-fp32-[H]x[W]-ox.tz2","ldclc-v1-fp16-[H]x[W]-ox.tz2"]` | `[96,96]` | `["sample","netOutput"]` |
| onnx_qnn | `imcc` | 0 | 8 | `["[N]-v[V]-fp16-[H]x[W]-v73-qnn-ox.tz2","ldclc-v1-fp16-[H]x[W]-qnn-ox.tz2"]` | `[96,96]` | `["sample","netOutput"]` |
| coreml | `imcc` | 0 | 8 | `["[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz","ldclc-v1-fp16-[H]x[W]-rev1-mlc.tz"]` | `[96,96]` | `["sample","netOutput"]` |
| tensorrt | `imcc` | 0 | 8 | `["[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2","ldclc-v1-fp32-[H]x[W]-rt[C]-rt.tz2"]` | `[96,96]` | `["sample","netOutput"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "rxl_decoder0",
  "name": "RecoveryXLD0",
  "category": "Enhance",
  "verb": "Enhancing",
  "enabled": 1,
  "optional": 1,
  "zeroCenter": 2,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 48,
  "blockDiscard": 11,
  "inputs": {
    "input": "latent_sample",
    "cinput": "netRef",
    "output": "netInput"
  },
  "backends": {
    "onnx16": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 20,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2",
            "ldclc-v1-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 20,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2",
            "ldclc-v1-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 74,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-v73-qnn-ox.tz2",
            "ldclc-v1-fp16-[H]x[W]-qnn-ox.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 0,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 41,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz",
            "ldclc-v1-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 20,
      "capabilities": [
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2",
            "ldclc-v1-fp32-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "sample",
            "netOutput"
          ]
        }
      }
    }
  }
}
```

</details>

### rxl_decoder1.json

#### 基础信息

```json
{
  "name": "RecoveryXLD1",
  "shortName": "rxl_decoder1",
  "category": "Enhance",
  "version": "1",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "latent_sample"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| onnx16 | `imn` | 0 | 8 | `"[N]-v[V]-fp16-[H]x[W]-ox.tz2"` | `[120,120]` | `"sample"` |
| onnx | `imn` | 0 | 8 | `"[N]-v[V]-fp32-[H]x[W]-ox.tz2"` | `[120,120]` | `"sample"` |
| onnx_qnn | `imn` | 0 | 8 | `"[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"` | `[120,120]` | `"sample"` |
| coreml | `imn` | 0 | 8 | `"[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz"` | `[120,120]` | `"sample"` |
| tensorrt | `imn` | 0 | 8 | `"[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"` | `[120,120]` | `"sample"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "rxl_decoder1",
  "name": "RecoveryXLD1",
  "category": "Enhance",
  "verb": "Enhancing",
  "enabled": 1,
  "optional": 1,
  "zeroCenter": 2,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 60,
  "blockDiscard": 11,
  "inputs": {
    "input": "latent_sample"
  },
  "backends": {
    "onnx16": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 30,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            120,
            120
          ],
          "outputs": [
            "sample"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 30,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            120,
            120
          ],
          "outputs": [
            "sample"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 132,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"
          ],
          "blocks": [
            120,
            120
          ],
          "outputs": [
            "sample"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": 0,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 704,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            120,
            120
          ],
          "outputs": [
            "sample"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 30,
      "capabilities": [
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            120,
            120
          ],
          "outputs": [
            "sample"
          ]
        }
      }
    }
  }
}
```

</details>

### rxl_embed.json

#### 基础信息

```json
{
  "name": "RecoveryXL Embed",
  "shortName": "rxl_embed",
  "category": "Enhance",
  "version": "1",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "input_ids"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `no` | -1 | 1 | `["[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz","rxl_vocab.txt","rxl_merges.txt","neg_emb.yaml"]` | `[768,77]` | `"last_hidden_state"` |
| onnx | `no` | 0 | 1 | `["[N]-v[V]-fp16-[H]x[W]-ox.tz2","rxl_vocab.txt","rxl_merges.txt","neg_emb.yaml"]` | `[768,77]` | `"last_hidden_state"` |
| openvino16 | `no` | 0 | 1 | `["[N]-v[V]-fp16-[H]x[W]-ox.tz2","rxl_vocab.txt","rxl_merges.txt","neg_emb.yaml"]` | `[768,77]` | `"last_hidden_state"` |
| tensorrt | `no` | 0 | 1 | `["[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2","rxl_vocab.txt","rxl_merges.txt","neg_emb.yaml"]` | `[768,77]` | `"last_hidden_state"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "rxl_embed",
  "name": "RecoveryXL Embed",
  "category": "Enhance",
  "verb": "Enhancing",
  "enabled": 1,
  "optional": 1,
  "inputs": {
    "input": "input_ids"
  },
  "backends": {
    "coreml": {
      "model": "no",
      "parallel": -1,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz",
            "rxl_vocab.txt",
            "rxl_merges.txt",
            "neg_emb.yaml"
          ],
          "blocks": [
            768,
            77
          ],
          "outputs": [
            "last_hidden_state"
          ]
        }
      }
    },
    "onnx": {
      "model": "no",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2",
            "rxl_vocab.txt",
            "rxl_merges.txt",
            "neg_emb.yaml"
          ],
          "blocks": [
            768,
            77
          ],
          "outputs": [
            "last_hidden_state"
          ]
        }
      }
    },
    "openvino16": {
      "model": "no",
      "parallel": 0,
      "transpose": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2",
            "rxl_vocab.txt",
            "rxl_merges.txt",
            "neg_emb.yaml"
          ],
          "blocks": [
            768,
            77
          ],
          "outputs": [
            "last_hidden_state"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "no",
      "parallel": 0,
      "capabilities": [
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2",
            "rxl_vocab.txt",
            "rxl_merges.txt",
            "neg_emb.yaml"
          ],
          "blocks": [
            768,
            77
          ],
          "outputs": [
            "last_hidden_state"
          ]
        }
      }
    }
  }
}
```

</details>

### rxl_encoder0.json

#### 基础信息

```json
{
  "name": "RecoveryXLE0",
  "shortName": "rxl_encoder0",
  "category": "Enhance",
  "version": "1",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "sample"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| onnx16 | `imn` | 0 | 0.125 | `"[N]-v[V]-fp16-[H]x[W]-ox.tz2"` | `[768,768]` | `"latent_sample"` |
| onnx | `imn` | 0 | 0.125 | `"[N]-v[V]-fp32-[H]x[W]-ox.tz2"` | `[768,768]` | `"latent_sample"` |
| onnx_qnn | `imn` | 0 | 0.125 | `"[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"` | `[768,768]` | `"latent_sample"` |
| coreml | `imn` | 0 | 0.125 | `"[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz"` | `[768,768]` | `"latent_sample"` |
| tensorrt | `imn` | 0 | 0.125 | `"[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"` | `[768,768]` | `"latent_sample"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "rxl_encoder0",
  "name": "RecoveryXLE0",
  "category": "Enhance",
  "verb": "Enhancing",
  "enabled": 1,
  "optional": 1,
  "zeroCenter": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 384,
  "blockDiscard": 32,
  "inputs": {
    "input0": "sample"
  },
  "backends": {
    "onnx16": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 9,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            768,
            768
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 9,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            768,
            768
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 35,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"
          ],
          "blocks": [
            768,
            768
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": 0,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 21,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            768,
            768
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 9,
      "capabilities": [
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            768,
            768
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    }
  }
}
```

</details>

### rxl_encoder1.json

#### 基础信息

```json
{
  "name": "RecoveryXLE1",
  "shortName": "rxl_encoder1",
  "category": "Enhance",
  "version": "1",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "sample"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| onnx16 | `imn` | 0 | 0.125 | `"[N]-v[V]-fp16-[H]x[W]-ox.tz2"` | `[960,960]` | `"latent_sample"` |
| onnx | `imn` | 0 | 0.125 | `"[N]-v[V]-fp32-[H]x[W]-ox.tz2"` | `[960,960]` | `"latent_sample"` |
| onnx_qnn | `imn` | 0 | 0.125 | `"[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"` | `[960,960]` | `"latent_sample"` |
| coreml | `imn` | 0 | 0.125 | `"[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz"` | `[960,960]` | `"latent_sample"` |
| tensorrt | `imn` | 0 | 0.125 | `"[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"` | `[960,960]` | `"latent_sample"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "rxl_encoder1",
  "name": "RecoveryXLE1",
  "category": "Enhance",
  "verb": "Enhancing",
  "enabled": 1,
  "optional": 1,
  "zeroCenter": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 480,
  "blockDiscard": 32,
  "inputs": {
    "input0": "sample"
  },
  "backends": {
    "onnx16": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 17,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            960,
            960
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 17,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            960,
            960
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 70,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-qnn-ox.tz2"
          ],
          "blocks": [
            960,
            960
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "coreml": {
      "model": "imn",
      "parallel": 0,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 35,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            960,
            960
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 17,
      "capabilities": [
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            960,
            960
          ],
          "outputs": [
            "latent_sample"
          ]
        }
      }
    }
  }
}
```

</details>

### rxl_unet0.json

#### 基础信息

```json
{
  "name": "RecoveryXLU0",
  "shortName": "rxl_unet0",
  "category": "Enhance",
  "version": "2",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "sample",
  "input1": "encoder_hidden_states",
  "input2": "controlnet_cond",
  "conditioning_scale": "conditioning_scale",
  "timestep": "timestep"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | -1 | 1 | `"[N]-v[V]-fp16-rev2-mlc.tz"` | `[0,0]` | `"noise_pred"` |
| onnx16 | `imn` | -1 | 1 | `["[N]-v[V]-fp16-ox.tz2","[N]-v[V]-fp16.pb"]` | `[0,0]` | `"m/out_sample"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "2",
  "minAppVersion": "0",
  "shortName": "rxl_unet0",
  "name": "RecoveryXLU0",
  "category": "Enhance",
  "verb": "Enhancing",
  "enabled": 1,
  "optional": 1,
  "blockOverlap": 0,
  "blockDiscard": 0,
  "blockPadExact": 0,
  "padding": [
    0,
    0
  ],
  "inputs": {
    "input0": "sample",
    "input1": "encoder_hidden_states",
    "input2": "controlnet_cond",
    "conditioning_scale": "conditioning_scale",
    "timestep": "timestep"
  },
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": -1,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 33,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-rev2-mlc.tz"
          ],
          "blocks": [
            0,
            0
          ],
          "outputs": [
            "noise_pred"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imn",
      "parallel": -1,
      "external": 1,
      "blockProcTime": 9,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-ox.tz2",
            "[N]-v[V]-fp16.pb"
          ],
          "blocks": [
            0,
            0
          ],
          "outputs": [
            "m/out_sample"
          ]
        }
      }
    }
  }
}
```

</details>

### rxl_unet1.json

#### 基础信息

```json
{
  "name": "RecoveryXLU1",
  "shortName": "rxl_unet1",
  "category": "Enhance",
  "version": "2",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "sample",
  "input1": "encoder_hidden_states",
  "input2": "controlnet_cond",
  "conditioning_scale": "conditioning_scale",
  "timestep": "timestep"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | -1 | 1 | `"[N]-v[V]-fp16-rev3-mlc.tz"` | `[0,0]` | `"noise_pred"` |
| onnx16 | `imn` | -1 | 1 | `["[N]-v[V]-fp16-ox.tz2","[N]-v[V]-fp16.pb"]` | `[0,0]` | `"m/out_sample"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "2",
  "minAppVersion": "0",
  "shortName": "rxl_unet1",
  "name": "RecoveryXLU1",
  "category": "Enhance",
  "verb": "Enhancing",
  "enabled": 1,
  "optional": 1,
  "blockOverlap": 0,
  "blockDiscard": 0,
  "blockPadExact": 0,
  "padding": [
    0,
    0
  ],
  "inputs": {
    "input0": "sample",
    "input1": "encoder_hidden_states",
    "input2": "controlnet_cond",
    "conditioning_scale": "conditioning_scale",
    "timestep": "timestep"
  },
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": -1,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 61,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-rev3-mlc.tz"
          ],
          "blocks": [
            0,
            0
          ],
          "outputs": [
            "noise_pred"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imn",
      "parallel": -1,
      "external": 1,
      "blockProcTime": 18,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-ox.tz2",
            "[N]-v[V]-fp16.pb"
          ],
          "blocks": [
            0,
            0
          ],
          "outputs": [
            "m/out_sample"
          ]
        }
      }
    }
  }
}
```

</details>

### ssddec0_0.json

#### 基础信息

```json
{
  "name": "SingleStepSharpenDecLow",
  "shortName": "ssddec0_0",
  "category": "Super Focus",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "z",
  "cinput": "netRef",
  "output": "netInput"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imcc` | 1 | 8 | `["[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz","ldclc-v1-fp16-[H]x[W]-rev1-mlc.tz"]` | `[64,64]` | `["image","netOutput"]` |
| onnx | `imcc` | 0 | 8 | `["[N]-v[V]-fp32-[H]x[W]-ox.tz2","ldclc-v1-fp32-[H]x[W]-ox.tz2"]` | `[64,64]` | `["image","netOutput"]` |
| onnx16 | `imcc` | 0 | 8 | `["[N]-v[V]-fp16-[H]x[W]-ox.tz2","ldclc-v1-fp16-[H]x[W]-ox.tz2"]` | `[64,64]` | `["image","netOutput"]` |
| openvino16 | `imcc` | 1 | 8 | `["[N]-v[V]-fp16-[H]x[W]-ov.tz2","ldclc-v1-fp16-[H]x[W]-ov.tz2"]` | `[64,64]` | `["image","netOutput"]` |
| tensorrt | `imcc` | 1 | 8 | `["[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2","ldclc-v1-fp16-[H]x[W]-rt[C]-rt.tz2"]` | `[96,96]` | `["image","netOutput"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "ssddec0_0",
  "name": "SingleStepSharpenDecLow",
  "category": "Super Focus",
  "enabled": 3,
  "optional": 1,
  "zeroCenter": 2,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 24,
  "blockDiscard": 6,
  "inputs": {
    "input": "z",
    "cinput": "netRef",
    "output": "netInput"
  },
  "backends": {
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 32,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz",
            "ldclc-v1-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 9,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2",
            "ldclc-v1-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 9,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2",
            "ldclc-v1-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    },
    "openvino16": {
      "model": "imcc",
      "parallel": 1,
      "blockProcTime": 58,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ov.tz2",
            "ldclc-v1-fp16-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 1,
      "blockProcTime": 9,
      "capabilities": [
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2",
            "ldclc-v1-fp16-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    }
  }
}
```

</details>

### ssddec0_5.json

#### 基础信息

```json
{
  "name": "SingleStepSharpenDecMid",
  "shortName": "ssddec0_5",
  "category": "Super Focus",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "z",
  "cinput": "netRef",
  "output": "netInput"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imcc` | 1 | 8 | `["[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz","ldclc-v1-fp16-[H]x[W]-rev1-mlc.tz"]` | `[64,64]` | `["image","netOutput"]` |
| onnx | `imcc` | 0 | 8 | `["[N]-v[V]-fp32-[H]x[W]-ox.tz2","ldclc-v1-fp32-[H]x[W]-ox.tz2"]` | `[64,64]` | `["image","netOutput"]` |
| onnx16 | `imcc` | 0 | 8 | `["[N]-v[V]-fp16-[H]x[W]-ox.tz2","ldclc-v1-fp16-[H]x[W]-ox.tz2"]` | `[64,64]` | `["image","netOutput"]` |
| openvino16 | `imcc` | 1 | 8 | `["[N]-v[V]-fp16-[H]x[W]-ov.tz2","ldclc-v1-fp16-[H]x[W]-ov.tz2"]` | `[64,64]` | `["image","netOutput"]` |
| tensorrt | `imcc` | 1 | 8 | `["[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2","ldclc-v1-fp16-[H]x[W]-rt[C]-rt.tz2"]` | `[96,96]` | `["image","netOutput"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "ssddec0_5",
  "name": "SingleStepSharpenDecMid",
  "category": "Super Focus",
  "enabled": 3,
  "optional": 1,
  "zeroCenter": 2,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 24,
  "blockDiscard": 6,
  "inputs": {
    "input": "z",
    "cinput": "netRef",
    "output": "netInput"
  },
  "backends": {
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 32,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz",
            "ldclc-v1-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 9,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2",
            "ldclc-v1-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 9,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2",
            "ldclc-v1-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    },
    "openvino16": {
      "model": "imcc",
      "parallel": 1,
      "blockProcTime": 58,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ov.tz2",
            "ldclc-v1-fp16-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 1,
      "blockProcTime": 9,
      "capabilities": [
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2",
            "ldclc-v1-fp16-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    }
  }
}
```

</details>

### ssddec1_0.json

#### 基础信息

```json
{
  "name": "SingleStepSharpenDecHigh",
  "shortName": "ssddec1_0",
  "category": "Super Focus",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "z",
  "cinput": "netRef",
  "output": "netInput"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imcc` | 1 | 8 | `["[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz","ldclc-v1-fp16-[H]x[W]-rev1-mlc.tz"]` | `[64,64]` | `["image","netOutput"]` |
| onnx | `imcc` | 0 | 8 | `["[N]-v[V]-fp32-[H]x[W]-ox.tz2","ldclc-v1-fp32-[H]x[W]-ox.tz2"]` | `[64,64]` | `["image","netOutput"]` |
| onnx16 | `imcc` | 0 | 8 | `["[N]-v[V]-fp16-[H]x[W]-ox.tz2","ldclc-v1-fp16-[H]x[W]-ox.tz2"]` | `[64,64]` | `["image","netOutput"]` |
| openvino16 | `imcc` | 1 | 8 | `["[N]-v[V]-fp16-[H]x[W]-ov.tz2","ldclc-v1-fp16-[H]x[W]-ov.tz2"]` | `[64,64]` | `["image","netOutput"]` |
| tensorrt | `imcc` | 1 | 8 | `["[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2","ldclc-v1-fp16-[H]x[W]-rt[C]-rt.tz2"]` | `[96,96]` | `["image","netOutput"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "ssddec1_0",
  "name": "SingleStepSharpenDecHigh",
  "category": "Super Focus",
  "enabled": 3,
  "optional": 1,
  "zeroCenter": 2,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 24,
  "blockDiscard": 6,
  "inputs": {
    "input": "z",
    "cinput": "netRef",
    "output": "netInput"
  },
  "backends": {
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 32,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz",
            "ldclc-v1-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 9,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-ox.tz2",
            "ldclc-v1-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 0,
      "blockProcTime": 9,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2",
            "ldclc-v1-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    },
    "openvino16": {
      "model": "imcc",
      "parallel": 1,
      "blockProcTime": 58,
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ov.tz2",
            "ldclc-v1-fp16-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "parallel": 1,
      "blockProcTime": 9,
      "capabilities": [
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "8": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2",
            "ldclc-v1-fp16-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "image",
            "netOutput"
          ]
        }
      }
    }
  }
}
```

</details>

### ssdenc-gpu-mac.json

#### 基础信息

```json
{
  "name": "SingleStepResizeEnc GPU Mac",
  "shortName": "ssdenc-gpu-mac",
  "category": "Enhance",
  "version": "1",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "x"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | -2 | 0.125 | `["ssdenc-v[V]-fp16-[H]x[W]-mlc.tz","default_prompt.bin"]` | `[512,512]` | `"latent"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "ssdenc-gpu-mac",
  "name": "SingleStepResizeEnc GPU Mac",
  "category": "Enhance",
  "enabled": 1,
  "optional": 1,
  "zeroCenter": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 64,
  "blockDiscard": 8,
  "inputs": {
    "input": "x"
  },
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": -2,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 13,
      "scales": {
        "0.125": {
          "nets": [
            "ssdenc-v[V]-fp16-[H]x[W]-mlc.tz",
            "default_prompt.bin"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "latent"
          ]
        }
      }
    }
  }
}
```

</details>

### ssdenc.json

#### 基础信息

```json
{
  "name": "SingleStepResizeEnc",
  "shortName": "ssdenc",
  "category": "Enhance",
  "version": "1",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input": "x"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | 1 | 0.125 | `["[N]-v[V]-fp16-[H]x[W]-mlc.tz","default_prompt.bin"]` | `[512,512]` | `"latent"` |
| onnx | `imn` | 0 | 0.125 | `["[N]-v[V]-fp16-[H]x[W]-ox.tz2","default_prompt.bin"]` | `[512,512]` | `"latent"` |
| openvino16 | `imn` | 0 | 0.125 | `["[N]-v[V]-fp16-[H]x[W]-ov.tz2","default_prompt.bin"]` | `[512,512]` | `"latent"` |
| tensorrt | `imn` | 1 | 0.125 | `["[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2","default_prompt.bin"]` | `[768,768]` | `"latent"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "ssdenc",
  "name": "SingleStepResizeEnc",
  "category": "Enhance",
  "enabled": 1,
  "optional": 1,
  "zeroCenter": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 64,
  "blockDiscard": 8,
  "inputs": {
    "input": "x"
  },
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": 1,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 13,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-mlc.tz",
            "default_prompt.bin"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "latent"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 6,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2",
            "default_prompt.bin"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "latent"
          ]
        }
      }
    },
    "openvino16": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 28,
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ov.tz2",
            "default_prompt.bin"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "latent"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 1,
      "blockProcTime": 6,
      "capabilities": [
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "0.125": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2",
            "default_prompt.bin"
          ],
          "blocks": [
            768,
            768
          ],
          "outputs": [
            "latent"
          ]
        }
      }
    }
  }
}
```

</details>

### ssdunet-gpu-mac.json

#### 基础信息

```json
{
  "name": "SingelStepResizeUnet GPU Mac",
  "shortName": "ssdunet-gpu-mac",
  "category": "Enhance",
  "version": "1",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "sample",
  "input1": "encoder_hidden_states"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | -2 | 1 | `"ssdunet-sharpen-v[V]-fp16-[H]x[W]-rev1-mlc.tz"` | `[64,64]` | `"noise_pred"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "ssdunet-gpu-mac",
  "name": "SingelStepResizeUnet GPU Mac",
  "category": "Enhance",
  "enabled": 1,
  "optional": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 32,
  "blockDiscard": 0,
  "inputs": {
    "input0": "sample",
    "input1": "encoder_hidden_states"
  },
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": -2,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 18,
      "scales": {
        "1": {
          "nets": [
            "ssdunet-sharpen-v[V]-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "noise_pred"
          ]
        }
      }
    }
  }
}
```

</details>

### ssdunet.json

#### 基础信息

```json
{
  "name": "SingelStepResizeUnet",
  "shortName": "ssdunet",
  "category": "Enhance",
  "version": "1",
  "enabled": 1,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "sample",
  "input1": "encoder_hidden_states"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz"` | `[64,64]` | `"noise_pred"` |
| onnx | `imn` | 0 | 1 | `["[N]-v[V]-fp32-[H]x[W]-rev1-ox.tz2","[N]-v[V]-fp32-[H]x[W]-rev1.onnx.data"]` | `[64,64]` | `"noise_pred"` |
| onnx16 | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-ox.tz2"` | `[64,64]` | `"noise_pred"` |
| openvino16 | `imn` | 1 | 1 | `"[N]-v[V]-fp16-[H]x[W]-ov.tz2"` | `[64,64]` | `"noise_pred"` |
| tensorrt | `imn` | 0 | 1 | `"[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2"` | `[96,96]` | `"noise_pred"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "ssdunet",
  "name": "SingelStepResizeUnet",
  "category": "Enhance",
  "enabled": 1,
  "optional": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 32,
  "blockDiscard": 0,
  "inputs": {
    "input0": "sample",
    "input1": "encoder_hidden_states"
  },
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": 1,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 18,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rev1-mlc.tz"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "noise_pred"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 0,
      "external": 1,
      "blockProcTime": 6,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-rev1-ox.tz2",
            "[N]-v[V]-fp32-[H]x[W]-rev1.onnx.data"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "noise_pred"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 6,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "noise_pred"
          ]
        }
      }
    },
    "openvino16": {
      "model": "imn",
      "parallel": 1,
      "blockProcTime": 22,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            64,
            64
          ],
          "outputs": [
            "noise_pred"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 6,
      "capabilities": [
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            96,
            96
          ],
          "outputs": [
            "noise_pred"
          ]
        }
      }
    }
  }
}
```

</details>

### stdmax_noee.json

#### 基础信息

```json
{
  "name": "StandardMaxNoNeuralEngine",
  "shortName": "stdmax_noee",
  "category": "Enhance",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "sample"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | -1 | 4 | `"stdmax-v[V]-mixed-[H]x[W]-mlc.tz"` | `[128,128]` | `"noise_pred"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "stdmax_noee",
  "name": "StandardMaxNoNeuralEngine",
  "category": "Enhance",
  "enabled": 3,
  "optional": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 64,
  "blockDiscard": 0,
  "inputs": {
    "input0": "sample"
  },
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": -1,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "scales": {
        "4": {
          "nets": [
            "stdmax-v[V]-mixed-[H]x[W]-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "noise_pred"
          ]
        }
      }
    }
  }
}
```

</details>

### stdmax.json

#### 基础信息

```json
{
  "name": "StandardMax",
  "shortName": "stdmax",
  "category": "Enhance",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "input0": "sample"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | 0 | 4 | `"[N]-v[V]-fp16-[H]x[W]-mlc.tz"` | `[192,192]` | `"noise_pred"` |
| onnx16 | `imn` | 0 | 4 | `"[N]-v[V]-fp16-[H]x[W]-ox.tz2"` | `[192,192]` | `"noise_pred"` |
| openvino16 | `imn` | 0 | 4 | `"[N]-v[V]-fp16-[H]x[W]-ov.tz2"` | `[192,192]` | `"noise_pred"` |
| tensorrt | `imn` | 0 | 4 | `"[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2"` | `[192,192]` | `"noise_pred"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "stdmax",
  "name": "StandardMax",
  "category": "Enhance",
  "verb": "Enhancing",
  "enabled": 3,
  "optional": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 96,
  "blockDiscard": 0,
  "inputs": {
    "input0": "sample"
  },
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": 0,
      "minMacVersion": 10.16,
      "supportsIntel": 0,
      "blockProcTime": 10,
      "scales": {
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-mlc.tz"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "noise_pred"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imn",
      "parallel": 0,
      "blockProcTime": 23,
      "scales": {
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "noise_pred"
          ]
        }
      }
    },
    "openvino16": {
      "model": "imn",
      "parallel": 0,
      "transpose": 0,
      "blockProcTime": 8,
      "scales": {
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "noise_pred"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imn",
      "parallel": 0,
      "capabilities": [
        "900-101401",
        "1200-101401"
      ],
      "scales": {
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            192,
            192
          ],
          "outputs": [
            "noise_pred"
          ]
        }
      }
    }
  }
}
```

</details>

### tpn_900_nogpu.json

#### 基础信息

```json
{
  "name": "NaturalUpscale900NoGpu",
  "shortName": "tpn_900_nogpu",
  "category": "Enhance",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "encInput": "input",
  "unetInput": "sample",
  "unetEmbeds": "encoder_hidden_states",
  "unetTimestep": "timestep",
  "decInput": "input",
  "clcInput": "netInput",
  "clcRef": "netRef"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imtpn` | 0 | 1 | `["tpn_enc-v[V]-fp16-[H]x[W]-mlc.tz","tpn_unet-v[V]-fp16-64x64-mlc.tz","tpn_dec-v[V]-fp16-64x64-mlc.tz","ldclc-v1-fp16-64x64-mlc.tz","tpn_embeds.bin"]` | `[512,512]` | `["output","out","output","netOutput"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "minAppVersion": "0",
  "shortName": "tpn_900_nogpu",
  "version": "1",
  "category": "Enhance",
  "name": "NaturalUpscale900NoGpu",
  "verb": "Enhancing",
  "generative": true,
  "enabled": 3,
  "optional": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 256,
  "blockDiscard": 0,
  "inputs": {
    "encInput": "input",
    "unetInput": "sample",
    "unetEmbeds": "encoder_hidden_states",
    "unetTimestep": "timestep",
    "decInput": "input",
    "clcInput": "netInput",
    "clcRef": "netRef"
  },
  "backends": {
    "coreml": {
      "model": "imtpn",
      "parallel": 0,
      "minMacVersion": 10.16,
      "scales": {
        "1": {
          "nets": [
            "tpn_enc-v[V]-fp16-[H]x[W]-mlc.tz",
            "tpn_unet-v[V]-fp16-64x64-mlc.tz",
            "tpn_dec-v[V]-fp16-64x64-mlc.tz",
            "ldclc-v1-fp16-64x64-mlc.tz",
            "tpn_embeds.bin"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "output",
            "out",
            "output",
            "netOutput"
          ]
        }
      }
    }
  }
}
```

</details>

### tpn_900.json

#### 基础信息

```json
{
  "name": "NaturalUpscale900",
  "shortName": "tpn_900",
  "category": "Enhance",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "encInput": "input",
  "unetInput": "sample",
  "unetEmbeds": "encoder_hidden_states",
  "unetTimestep": "timestep",
  "decInput": "input",
  "clcInput": "netInput",
  "clcRef": "netRef"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imtpn` | 1 | 1 | `["tpn_enc-v[V]-fp16-[H]x[W]-mlc.tz","tpn_unet-v[V]-fp16-64x64-mlc.tz","tpn_dec-v[V]-fp16-64x64-mlc.tz","ldclc-v1-fp16-64x64-mlc.tz","tpn_embeds.bin"]` | `[512,512]` | `["output","out","output","netOutput"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "minAppVersion": "0",
  "shortName": "tpn_900",
  "version": "1",
  "category": "Enhance",
  "name": "NaturalUpscale900",
  "verb": "Enhancing",
  "generative": true,
  "enabled": 3,
  "optional": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 256,
  "blockDiscard": 0,
  "inputs": {
    "encInput": "input",
    "unetInput": "sample",
    "unetEmbeds": "encoder_hidden_states",
    "unetTimestep": "timestep",
    "decInput": "input",
    "clcInput": "netInput",
    "clcRef": "netRef"
  },
  "backends": {
    "coreml": {
      "model": "imtpn",
      "parallel": 1,
      "minMacVersion": 10.16,
      "scales": {
        "1": {
          "nets": [
            "tpn_enc-v[V]-fp16-[H]x[W]-mlc.tz",
            "tpn_unet-v[V]-fp16-64x64-mlc.tz",
            "tpn_dec-v[V]-fp16-64x64-mlc.tz",
            "ldclc-v1-fp16-64x64-mlc.tz",
            "tpn_embeds.bin"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "output",
            "out",
            "output",
            "netOutput"
          ]
        }
      }
    }
  }
}
```

</details>

### tpn_nogpu.json

#### 基础信息

```json
{
  "name": "NaturalUpscaleNoGpu",
  "shortName": "tpn_nogpu",
  "category": "Enhance",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "encInput": "input",
  "unetInput": "sample",
  "unetEmbeds": "encoder_hidden_states",
  "unetTimestep": "timestep",
  "decInput": "input",
  "clcInput": "netInput",
  "clcRef": "netRef"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imtpn` | 0 | 1 | `["tpn_enc-v[V]-fp16-[H]x[W]-mlc.tz","tpn_unet-v[V]-fp16-64x64-new-mlc.tz","tpn_dec-v[V]-fp16-64x64-mlc.tz","ldclc-v1-fp16-64x64-mlc.tz","tpn_embeds.bin"]` | `[512,512]` | `["output","out","output","netOutput"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "minAppVersion": "0",
  "shortName": "tpn_nogpu",
  "version": "1",
  "category": "Enhance",
  "name": "NaturalUpscaleNoGpu",
  "verb": "Enhancing",
  "generative": true,
  "enabled": 3,
  "optional": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 256,
  "blockDiscard": 0,
  "inputs": {
    "encInput": "input",
    "unetInput": "sample",
    "unetEmbeds": "encoder_hidden_states",
    "unetTimestep": "timestep",
    "decInput": "input",
    "clcInput": "netInput",
    "clcRef": "netRef"
  },
  "backends": {
    "coreml": {
      "model": "imtpn",
      "parallel": 0,
      "minMacVersion": 10.16,
      "scales": {
        "1": {
          "nets": [
            "tpn_enc-v[V]-fp16-[H]x[W]-mlc.tz",
            "tpn_unet-v[V]-fp16-64x64-new-mlc.tz",
            "tpn_dec-v[V]-fp16-64x64-mlc.tz",
            "ldclc-v1-fp16-64x64-mlc.tz",
            "tpn_embeds.bin"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "output",
            "out",
            "output",
            "netOutput"
          ]
        }
      }
    }
  }
}
```

</details>

### tpn.json

#### 基础信息

```json
{
  "name": "NaturalUpscale",
  "shortName": "tpn",
  "category": "Enhance",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "encInput": "input",
  "unetInput": "sample",
  "unetEmbeds": "encoder_hidden_states",
  "unetTimestep": "timestep",
  "decInput": "input",
  "clcInput": "netInput",
  "clcRef": "netRef"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imtpn` | 1 | 1 | `["[N]_enc-v[V]-fp16-[H]x[W]-mlc.tz","[N]_unet-v[V]-fp16-64x64-new-mlc.tz","[N]_dec-v[V]-fp16-64x64-mlc.tz","ldclc-v1-fp16-64x64-mlc.tz","tpn_embeds.bin"]` | `[512,512]` | `["output","out","output","netOutput"]` |
| onnx16 | `imtpn` | 0 | 1 | `["[N]_enc-v[V]-fp16-[H]x[W]-ox.tz2","[N]_unet-v[V]-fp16-64x64-ox.tz2","[N]_dec-v[V]-fp16-64x64-ox.tz2","ldclc-v1-fp16-64x64-ox.tz2","tpn_embeds.bin"]` | `[512,512]` | `["output","out_sample","output","netOutput"]` |
| openvino16 | `imtpn` | 0 | 1 | `["[N]_enc-v[V]-fp16-[H]x[W]-ox.tz2","[N]_unet-v[V]-fp16-64x64-ox.tz2","[N]_dec-v[V]-fp16-64x64-ox.tz2","ldclc-v1-fp16-64x64-ox.tz2","tpn_embeds.bin"]` | `[512,512]` | `["output","out_sample","output","netOutput"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "minAppVersion": "0",
  "shortName": "tpn",
  "version": "1",
  "category": "Enhance",
  "name": "NaturalUpscale",
  "verb": "Enhancing",
  "generative": true,
  "enabled": 3,
  "optional": 1,
  "padding": [
    0,
    0
  ],
  "blockOverlap": 256,
  "blockDiscard": 0,
  "inputs": {
    "encInput": "input",
    "unetInput": "sample",
    "unetEmbeds": "encoder_hidden_states",
    "unetTimestep": "timestep",
    "decInput": "input",
    "clcInput": "netInput",
    "clcRef": "netRef"
  },
  "backends": {
    "coreml": {
      "model": "imtpn",
      "parallel": 1,
      "minMacVersion": 10.16,
      "scales": {
        "1": {
          "nets": [
            "[N]_enc-v[V]-fp16-[H]x[W]-mlc.tz",
            "[N]_unet-v[V]-fp16-64x64-new-mlc.tz",
            "[N]_dec-v[V]-fp16-64x64-mlc.tz",
            "ldclc-v1-fp16-64x64-mlc.tz",
            "tpn_embeds.bin"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "output",
            "out",
            "output",
            "netOutput"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imtpn",
      "parallel": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]_enc-v[V]-fp16-[H]x[W]-ox.tz2",
            "[N]_unet-v[V]-fp16-64x64-ox.tz2",
            "[N]_dec-v[V]-fp16-64x64-ox.tz2",
            "ldclc-v1-fp16-64x64-ox.tz2",
            "tpn_embeds.bin"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "output",
            "out_sample",
            "output",
            "netOutput"
          ]
        }
      }
    },
    "openvino16": {
      "model": "imtpn",
      "parallel": 0,
      "transpose": 0,
      "scales": {
        "1": {
          "nets": [
            "[N]_enc-v[V]-fp16-[H]x[W]-ox.tz2",
            "[N]_unet-v[V]-fp16-64x64-ox.tz2",
            "[N]_dec-v[V]-fp16-64x64-ox.tz2",
            "ldclc-v1-fp16-64x64-ox.tz2",
            "tpn_embeds.bin"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "output",
            "out_sample",
            "output",
            "netOutput"
          ]
        }
      }
    }
  }
}
```

</details>

### trf.json

#### 基础信息

```json
{
  "name": "Text Refine",
  "shortName": "trf",
  "category": "Enhance",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "param1": "pn",
  "param2": "pb",
  "param3": "pc",
  "input": "netInput",
  "cinput": "infer_input",
  "output": "infer_output"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[128,128]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| openvino | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"]` | `[128,128]` | `["netOutput","model/tf.clip_by_value/clip_by_value"]` |
| onnx16 | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx16 | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| onnx_qnn | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2","gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| coreml | `imcc` | 1 | 2 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[128,128]` | `["netOutput","Identity"]` |
| coreml | `imcc` | 1 | 4 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"]` | `[128,128]` | `["netOutput","Identity"]` |
| tensorrt | `imcc` | 1 | 2 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |
| tensorrt | `imcc` | 1 | 4 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"]` | `[128,128]` | `["netOutput","tf.clip_by_value"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "trf",
  "blockOverlap": 32,
  "blockDiscard": 4,
  "enabled": 3,
  "optional": 1,
  "name": "Text Refine",
  "category": "Enhance",
  "verb": "Enhancing",
  "inputs": {
    "param1": "pn",
    "param2": "pb",
    "param3": "pc",
    "input": "netInput",
    "cinput": "infer_input",
    "output": "infer_output"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "gclc-v1-fp16-[H]x[W]-[S]x-ov.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "model/tf.clip_by_value/clip_by_value"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-v73-qnn-ox.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-ox.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "minMacVersion": 10.16,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "gclc-v1-fp16-[H]x[W]-[S]x-mlc.tz"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "parallel": 1,
      "scales": {
        "2": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        },
        "4": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "gclc-v1-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2"
          ],
          "blocks": [
            128,
            128
          ],
          "outputs": [
            "netOutput",
            "tf.clip_by_value"
          ]
        }
      }
    }
  },
  "cli": {
    "aliases": [
      "text",
      "txt",
      "text refine"
    ],
    "params": {
      "param1": "denoise",
      "param2": "sharpen",
      "param3": "compression"
    }
  }
}
```

</details>

### trfn.json

#### 基础信息

```json
{
  "name": "Text Refine Noisy",
  "shortName": "trfn",
  "category": "Enhance",
  "version": "1",
  "enabled": 3,
  "optional": 1,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{
  "param1": "pn",
  "param2": "pb",
  "input": "netInput",
  "cinput": "infer_input",
  "output": "infer_output"
}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| openvino | `imcc` | 1 | 1 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2","clc-v2-fp32-[H]x[W]-ov.tz2"]` | `[512,512]` | `["netOutput","Identity"]` |
| onnx16 | `imcc` | 1 | 1 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2","clc-v3-fp16-[H]x[W]-ox.tz2"]` | `[512,512]` | `["netOutput","Identity"]` |
| onnx | `imcc` | 1 | 1 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2","clc-v3-fp32-[H]x[W]-ox.tz2"]` | `[512,512]` | `["netOutput","Identity"]` |
| onnx_qnn | `imcc` | 1 | 1 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2","clc-v3-fp16-[H]x[W]-qnn-ox.tz2"]` | `[512,512]` | `["netOutput","Identity"]` |
| coreml | `imcc` | 1 | 1 | `["[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz","clc-v3-fp16-[H]x[W]-mlc.tz"]` | `[512,512]` | `["netOutput","Identity"]` |
| tensorrt | `imcc` | 1 | 1 | `["[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2","clc-v3-fp32-[H]x[W]-rt[C]-rt.tz2"]` | `[512,512]` | `["netOutput","Identity"]` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "xParams": {
    "xIgnore": true
  },
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "trfn",
  "blockOverlap": 48,
  "blockDiscard": 10,
  "enabled": 3,
  "optional": 1,
  "name": "Text Refine Noisy",
  "category": "Enhance",
  "verb": "Enhancing",
  "inputs": {
    "param1": "pn",
    "param2": "pb",
    "input": "netInput",
    "cinput": "infer_input",
    "output": "infer_output"
  },
  "backends": {
    "openvino": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ov.tz2",
            "clc-v2-fp32-[H]x[W]-ov.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    },
    "onnx16": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-ox.tz2",
            "clc-v3-fp16-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    },
    "onnx": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-ox.tz2",
            "clc-v3-fp32-[H]x[W]-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    },
    "onnx_qnn": {
      "model": "imcc",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-qnn-ox.tz2",
            "clc-v3-fp16-[H]x[W]-qnn-ox.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    },
    "coreml": {
      "model": "imcc",
      "parallel": 1,
      "minMacVersion": 10.16,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp16-[H]x[W]-[S]x-mlc.tz",
            "clc-v3-fp16-[H]x[W]-mlc.tz"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    },
    "tensorrt": {
      "model": "imcc",
      "capabilities": [
        "705-10800",
        "806-10800",
        "809-10800",
        "1200-10800",
        "900-101401",
        "1200-101401"
      ],
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "[N]-v[V]-fp32-[H]x[W]-[S]x-rt[C]-rt.tz2",
            "clc-v3-fp32-[H]x[W]-rt[C]-rt.tz2"
          ],
          "blocks": [
            512,
            512
          ],
          "outputs": [
            "netOutput",
            "Identity"
          ]
        }
      }
    }
  }
}
```

</details>

### wonder-2.json

#### 基础信息

```json
{
  "name": "Wonder 2",
  "shortName": "Wonder V2",
  "category": "Wonder V2",
  "version": "1",
  "enabled": 3,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | 1 | 1 | `"wonder-2-20260527-mac.zip"` | `[0,0]` | `"output"` |
| onnx | `imn` | 1 | 1 | `"wonder-2-20260527-win.zip"` | `[0,0]` | `"output"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "Wonder V2",
  "name": "Wonder 2",
  "category": "Wonder V2",
  "verb": "Enhancing",
  "enabled": 3,
  "optional": 0,
  "isNeuroserverModel": true,
  "validate_install": {
    "windows": {
      "model": {
        "version": "wonder-2-20260527-win.zip",
        "zipHash": "922e36792fb5eb4bae262d9404ea932369cb323443fa90645240c341bd6655a32ba1f786b0796b621b7df9bde232b7bf93a83a31ee832abfbbe247983a24d83b",
        "numFiles": 44,
        "masterHash": "5946248816cf814311056dba854cddfe917163c71e0ad9993a9b7d6d375ab4b1133afefdef014808c295f26f05e525a8d83db7c420b3b024cb2b0af62ec2b191"
      }
    },
    "mac": {
      "model": {
        "version": "wonder-2-20260527-mac.zip",
        "zipHash": "59f27fa63a132950393cc728b4ca7746e6772b93790a9a5d82cc8823be9895363c2e622647ccb832a9bcd25980b0e189922da6b9ed1cb2c649bf9b46b22c73e6",
        "numFiles": 43,
        "masterHash": "f83439b1a386ae39f1cd7db3277a8640cc8f98da2eb08ed2b2e96a34633e0fd65a91906812213374fd3adeccef3f2b5aa78267b36179b5653dc78140158abdb8"
      }
    }
  },
  "parameters": [],
  "inputs": {},
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "wonder-2-20260527-mac.zip"
          ],
          "blocks": [
            0,
            0
          ],
          "outputs": [
            "output"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "wonder-2-20260527-win.zip"
          ],
          "blocks": [
            0,
            0
          ],
          "outputs": [
            "output"
          ]
        }
      }
    }
  }
}
```

</details>

### wonder-3.5.json

#### 基础信息

```json
{
  "name": "Wonder 3.5",
  "shortName": "Wonder V3.5",
  "category": "Wonder V3.5",
  "version": "1",
  "enabled": 3,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| _NONE_ | `null` | null | null | `null` | `null` | `null` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "Wonder V3.5",
  "name": "Wonder 3.5",
  "category": "Wonder V3.5",
  "verb": "Enhancing",
  "enabled": 3,
  "optional": 0,
  "isNeuroserverModel": true,
  "parameters": [
    {
      "name": "enhancement_strength",
      "allowedValue": [
        0.7,
        1.0,
        1.3
      ],
      "defaultValue": 1.0
    },
    {
      "name": "upscale_factor",
      "requiresRounding": true
    }
  ],
  "inputs": {},
  "backends": {}
}
```

</details>

### wonder-3.json

#### 基础信息

```json
{
  "name": "Wonder 3",
  "shortName": "Wonder V3",
  "category": "Wonder V3",
  "version": "1",
  "enabled": 3,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | 1 | 1 | `"wonder-all-20260512.zip"` | `[0,0]` | `"output"` |
| onnx | `imn` | 1 | 1 | `"wonder-all-20260512.zip"` | `[0,0]` | `"output"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "Wonder V3",
  "name": "Wonder 3",
  "category": "Wonder V3",
  "verb": "Enhancing",
  "enabled": 3,
  "optional": 0,
  "isNeuroserverModel": true,
  "validate_install": {
    "windows": {
      "model": {
        "version": "wonder-all-20260728-win.zip",
        "zipHash": "d15316d9f0c91a5b03aa60f3a2cff802afe66ce946032f11faeb903d16e0af32db4a2fcc8e1fa7f483634de9ecbf1de28eae61cd3240a7c35ade1f1829b0ae8e",
        "numFiles": 48,
        "masterHash": "d7f440542bf0dbee71022890dd2ada6f686b0eeccd3316ba0e318d214c93f4fbb6e9251f19e8603bdcb2394f0128dc284c9beed56570870c0f344e5c7f49a393"
      }
    },
    "mac": {
      "model": {
        "version": "wonder-all-20260728-mac.zip",
        "zipHash": "55ff748ee4c2a46fc7a5575c99628944faa950c75423eeacbde51d81a595bbbdc000ac6072c0a2950bd29f5c6a15b4e21020084c259eb5e98af9d581ef76ef49",
        "numFiles": 47,
        "masterHash": "fb41c15afc14abebb0288760f144a32903f9f288d0cc7fb3e206bdea9d8ed3b408d7c704ff39bb48908fe49d035210e8dc7adec055485b9b9709f41c9ec48634"
      }
    }
  },
  "parameters": [
    {
      "name": "enhancement_strength",
      "allowedValue": [
        0.7,
        1.0,
        1.3
      ],
      "defaultValue": 1.0
    },
    {
      "name": "upscale_factor",
      "requiresRounding": true
    }
  ],
  "inputs": {},
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "wonder-all-20260512.zip"
          ],
          "blocks": [
            0,
            0
          ],
          "outputs": [
            "output"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "wonder-all-20260512.zip"
          ],
          "blocks": [
            0,
            0
          ],
          "outputs": [
            "output"
          ]
        }
      }
    }
  }
}
```

</details>

### wonder-all.json

#### 基础信息

```json
{
  "name": "Wonder All",
  "shortName": "Wonder All",
  "category": "Wonder All",
  "version": "1",
  "enabled": 3,
  "optional": 0,
  "autoModel": null
}
```

#### inputs 完整映射

```json
{}
```

#### backend 矩阵

| backend | model | parallel | scale | nets | blocks | outputs |
|---|---|---:|---:|---|---|---|
| coreml | `imn` | 1 | 1 | `"wonder-all-20260728-mac.zip"` | `[0,0]` | `"output"` |
| onnx | `imn` | 1 | 1 | `"wonder-all-20260728-win.zip"` | `[0,0]` | `"output"` |

<details>
<summary>完整解析对象（无字段省略）</summary>

```json
{
  "jsonVersion": "1.0.0",
  "version": "1",
  "minAppVersion": "0",
  "shortName": "Wonder All",
  "name": "Wonder All",
  "category": "Wonder All",
  "verb": "Enhancing",
  "enabled": 3,
  "optional": 0,
  "isNeuroserverModel": true,
  "validate_install": {
    "windows": {
      "model": {
        "version": "wonder-all-20260728-win.zip",
        "zipHash": "d15316d9f0c91a5b03aa60f3a2cff802afe66ce946032f11faeb903d16e0af32db4a2fcc8e1fa7f483634de9ecbf1de28eae61cd3240a7c35ade1f1829b0ae8e",
        "numFiles": 48,
        "masterHash": "d7f440542bf0dbee71022890dd2ada6f686b0eeccd3316ba0e318d214c93f4fbb6e9251f19e8603bdcb2394f0128dc284c9beed56570870c0f344e5c7f49a393"
      }
    },
    "mac": {
      "model": {
        "version": "wonder-all-20260728-mac.zip",
        "zipHash": "55ff748ee4c2a46fc7a5575c99628944faa950c75423eeacbde51d81a595bbbdc000ac6072c0a2950bd29f5c6a15b4e21020084c259eb5e98af9d581ef76ef49",
        "numFiles": 47,
        "masterHash": "fb41c15afc14abebb0288760f144a32903f9f288d0cc7fb3e206bdea9d8ed3b408d7c704ff39bb48908fe49d035210e8dc7adec055485b9b9709f41c9ec48634"
      }
    }
  },
  "parameters": [
    {
      "name": "enhancement_strength",
      "allowedValue": [
        0.7,
        1.0,
        1.3
      ],
      "defaultValue": 1.0
    },
    {
      "name": "scale",
      "requiresRounding": true
    }
  ],
  "inputs": {},
  "backends": {
    "coreml": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "wonder-all-20260728-mac.zip"
          ],
          "blocks": [
            0,
            0
          ],
          "outputs": [
            "output"
          ]
        }
      }
    },
    "onnx": {
      "model": "imn",
      "parallel": 1,
      "scales": {
        "1": {
          "nets": [
            "wonder-all-20260728-win.zip"
          ],
          "blocks": [
            0,
            0
          ],
          "outputs": [
            "output"
          ]
        }
      }
    }
  }
}
```

</details>

