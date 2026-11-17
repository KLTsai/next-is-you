# Automated reading of public hospital pages under Taiwan (R.O.C.) law

Research date: 2026-11-17.

> **This is source research by a non-lawyer. It is not legal advice.** It records what statutes, court decisions and agency letters say, and separately marks the researcher's own reading. Courts decide each case on its facts, and several of the questions below have no decision on comparable facts. Consult a Taiwan-qualified lawyer before relying on any of it.

Question: under Taiwan law, what does the law itself prohibit or permit for a private, non-commercial, family-only tool that reads public hospital pages (outpatient schedule and live queue progress) about once a minute for one clinic while one visit is watched, as distinct from what a site writes in a footer or `robots.txt`? The owner's position to be tested: "I will not do anything that violates the law; I want to know what the law clearly provides, not what a site says without legal effect."

Short answer, expanded below: the position is right that no statute, regulation or decision found gives a footer notice or `robots.txt` legal force by itself, and right that the statutory "no reproduction" sentence is a duty placed on hospitals. It is wrong in one respect that matters: Taiwan courts read "無故" in the computer-misuse chapter of the Criminal Code to include acting against the owner's will or beyond the scope the owner authorised, and one district court used a site's published usage rules, which banned automated querying, as part of finding "無故". A site statement is therefore not law, but it is evidence that can feed a legal element. The decisions that went against scrapers all involved competitors copying data in bulk into their own product; none found involves a private reader like the one in the facts. That gap is uncertainty, not clearance.

## Method

- Statute and regulation text was read on 全國法規資料庫 (law.moj.gov.tw), one article per request, on 2026-11-17. Text is quoted as displayed that day. Where the database shows an amended text that is not yet in force, that is stated.
- Court decisions were found by full-text search on 司法院裁判書系統 (judgment.judicial.gov.tw) and read there. Search terms used: 網路爬蟲; 爬蟲 with 妨害電腦使用, 無故取得, 第358條, 第360條, 服務條款 and 契約; robots.txt; 自動化程式; 驗證碼 with 破解使用電腦之保護措施; 訂票 with 第360條; and the wording of the Fair Trade Commission guideline on copied website data. About 20 searches and 35 decisions were opened. This is not an exhaustive survey. The system holds only published decisions; prosecutors' non-prosecution dispositions are mostly not in it.
- Copyright interpretations were searched and read on the 經濟部智慧財產局 copyright site (www.tipo.gov.tw/tw/copyright/692.html).
- Law-firm articles were used only as leads to find case numbers. Nothing below rests on them unless labelled "secondary source only".
- No hospital website was opened for this research. Site wording is taken from [hospital-schedule-and-progress-survey.md](hospital-schedule-and-progress-survey.md), section "Access terms across the sample".

Every finding carries one label:

- **[statute text]** - quoted from law.moj.gov.tw.
- **[court holding]** - read in the decision itself on judgment.judicial.gov.tw.
- **[agency interpretation]** - a letter or guideline of a government agency; where it was read somewhere other than the issuing agency's own site, that is said.
- **[secondary source only]** - not confirmed in a primary source.
- **[none found]** - searched for and not found; this is a statement about the search, not about the law.

Paragraphs headed **Reading** are the researcher's own application to the facts. They are not holdings.

The facts assumed throughout ("the facts"): pages any visitor can open without logging in; no CAPTCHA solved or bypassed; no patient identifier used; no undocumented endpoint probed; one clinic at a time, about one request a minute while a visit is watched, one schedule read at setup and one per day for saved drafts; only the matched clinic's current number kept transiently; nothing republished; a private message to a few invited family members; no charge; not offered to the public.

## Sources that could not be opened

- `topic.tipo.gov.tw` (the older TIPO copyright host) did not resolve. The same database was reached at www.tipo.gov.tw.
- 公平交易委員會: the guideline page for 公平交易委員會對於公平交易法第二十五條案件之處理原則 redirected to the site index, and the disposition texts 公處字第106084號 and 公處字第111070號 were not opened. The guideline is quoted below only as courts quote it.
- 法務部主管法規查詢系統 (mojlaw.moj.gov.tw): a search by letter number returned no result. The two personal-data letters below were read on 臺北市法規查詢系統 (laws.gov.taipei), a city government republication. The 個人資料保護委員會 site was not searched.
- 智慧財產法院 107年度民公訴字第8號 (first instance of the 591 case): the system returned no text ("案件目前繫屬法院或無該案號裁判書"). Its reasoning is known here only as the appeal decision restates it.
- 臺灣新竹地方法院 110年度智易字第4號 (first instance of the LiTV case) was not opened separately; the appeal decision restates it.
- TIPO letters 智著字第11400020950號 (2025-06-13) and the 2025-06-30 letter cited in 最高法院 114年度台非字第155號 were not opened.
- Legislative reasons for 刑法 第358條 to 第361條 and 個資法 第51條 were not opened at 立法院; they are quoted below only as a court or agency quotes them.
- No second-instance decision in the Lawsnote case (below) was found in the system. Whether an appeal is pending was not verified.
- No 衛生福利部 interpretation of 醫療機構網際網路資訊管理辦法 第4條 was found; the ministry's own interpretation database was not searched directly.

## 1. Criminal law: 刑法 第36章 妨害電腦使用罪

### What the text says

**[statute text]** 中華民國刑法, last amended 民國115年7月22日 (that amendment touched 第80條 only). <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=C0000001&flno=358> (change `flno` for 359 to 363)

- 第358條: "無故輸入他人帳號密碼、破解使用電腦之保護措施或利用電腦系統之漏洞，而入侵他人之電腦或其相關設備者，處三年以下有期徒刑、拘役或科或併科三十萬元以下罰金。"
- 第359條: "無故取得、刪除或變更他人電腦或其相關設備之電磁紀錄，致生損害於公眾或他人者，處五年以下有期徒刑、拘役或科或併科六十萬元以下罰金。"
- 第360條: "無故以電腦程式或其他電磁方式干擾他人電腦或其相關設備，致生損害於公眾或他人者，處三年以下有期徒刑、拘役或科或併科三十萬元以下罰金。"
- 第361條: "對於公務機關之電腦或其相關設備犯前三條之罪者，加重其刑至二分之一。"
- 第362條: "製作專供犯本章之罪之電腦程式，而供自己或他人犯本章之罪，致生損害於公眾或他人者，處五年以下有期徒刑、拘役或科或併科六十萬元以下罰金。"
- 第363條: "第三百五十八條至第三百六十條之罪，須告訴乃論。"

第358條 lists three means only (another person's account and password, cracking a protective measure, exploiting a vulnerability). 第359條 and 第360條 each require both "無故" and "致生損害於公眾或他人". 第358條 to 第360條 are prosecuted only on complaint (第363條).

### What courts have said the elements require

**"無故" and "取得".** **[court holding]** 最高法院 110年度台上字第90號刑事判決 (2021-07-15), an employee-data case, not a crawler case: "所謂「取得」，係指透過電腦等科技之使用，將他人電磁紀錄移轉為自己所有；所謂「無故」，係指無正當權源或正當事由。... 職是，包括「無正當理由」、「未經所有人許可」、「無處分權限」或「違反所有人意思」、「逾越授權範圍」等情，均屬「無故」。" <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPSM%2C110%2C%E5%8F%B0%E4%B8%8A%2C90%2C20210715%2C1>

**"致生損害".** **[court holding]** 最高法院 112年度台上字第1029號刑事判決 (2023-05-03), an email-deletion case: "所謂之「致生損害」，不以已經造成公眾或他人財產或經濟上利益之實質損失為限，若已破壞電磁紀錄處分權人對電磁紀錄獨有之支配、控制或完整使用，致有害於電磁紀錄所有人、處分權人或公眾之利益，即已該當。" <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPSM%2C112%2C%E5%8F%B0%E4%B8%8A%2C1029%2C20230503%2C1>

**"保護措施" and "入侵" (第358條).** **[court holding]** 智慧財產及商業法院 112年度刑智上易字第29號刑事判決 (2024-10-09): "立法者僅針對情節較重大之無故入侵行為處罰，即以盜用他人帳號密碼或破解相類似保護措施（例如：使用電腦程式解除帳號管理系統之限制），或利用電腦系統漏洞之方法（例如：順應電腦系統之防火牆程式漏洞而趁機入侵電腦系統）。倘若行為人係經由電腦系統資訊之處分權人授權而處於隨時可得進入電腦系統取得內部資訊之狀態，縱令其後對該等資訊有違約或不合目的使用之情事，仍非屬本罪之入侵行為。" <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=IPCM%2C112%2C%E5%88%91%E6%99%BA%E4%B8%8A%E6%98%93%2C29%2C20241009%2C2>

**"干擾" (第360條).** **[court holding]** Same decision: the offence "僅針對妨害電腦系統本身正常處理電磁紀錄，並對於電腦及網路設備資訊處理功能之正常運作產生重大影響者，例如植入惡意程式造成他人電腦無法使用、使用「封包洪流」（Ping Flood）或「分散式阻斷服務攻擊」... 造成電腦系統當機、暫停運作或網路癱瘓". The legislative reason, as quoted in 臺灣高等法院花蓮分院 107年度上訴字第55號刑事判決 (2019-05-31): "本條處罰之對象乃對電腦及網路設備產生重大影響之故意干擾行為，為避免某些對電腦系統僅產生極輕度影響之測試或運用行為亦被繩以本罪，故加上「致生損害於公眾或他人」之要件，以免刑罰範圍過於擴張。" <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=HLHM%2C107%2C%E4%B8%8A%E8%A8%B4%2C55%2C20190531%2C1>

### Decisions on crawlers and automated queries

Four matters were found. They do not point one way.

**(a) Conviction: Lawsnote / 法源法律網.** **[court holding]** 臺灣新北地方法院 111年度智訴字第8號刑事判決 (2025-06-24), first instance. <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=PCDM%2C111%2C%E6%99%BA%E8%A8%B4%2C8%2C20250624%2C2>

- Parties: prosecution of 七法股份有限公司 (Lawsnote), its representative and its engineer; complainant 法源資訊股份有限公司, a competing legal database.
- What was taken: six crawler programs downloaded, from the complainant's website, 98,068 statute-history records (held to be a protected 編輯著作) plus 102,520 statute texts and 130,936 attachments (held not copyrighted), 331,524 electromagnetic records in all, loaded into the defendants' paid database.
- Use: commercial, by a direct competitor, sold by subscription.
- Held: guilty of 著作權法 第91條第2項 for the statute histories and of 刑法 第359條 無故取得他人電腦電磁紀錄 for all three sets, including the uncopyrightable ones. Sentences of four years and two years, and a fine on the company. On "無故" the court quoted the site's 使用規範, which excluded "以程式或自動化方式執行查詢、下載、擷取內容…等方式，使用本網站" and "將「法源法律網」之內容，載入自行或他人開發之系統中，充作資料庫之部分或全部", found the defendants knew those rules, and concluded: "被告等以系爭爬蟲程式自動化擷取「法源法律網」網站內容，並以電磁紀錄之格式重製於自行開發之系統中，充作七法資料庫內之法學資料，並於市場上販售供人使用且以之與告訴人公司競爭。此等行為顯然無正當理由、無處分權限，除未經告訴人法源公司許可，也違反告訴人法源公司意思，亦明顯逾越告訴人「法源法律網」使用規範之授權範圍，致被告等人因不用付出建置系爭資料的任何成本，而得以在市場上爭取客戶，有可能使告訴人公司的商業利益或機會受到不利的影響，致生損害於告訴人公司。"
- The defence that the material was government information was rejected: the complainant is a private company and 政府資訊公開法 binds government.
- The attached civil judgment, 臺灣新北地方法院 112年度智重附民字第1號 (same date), ordered joint payment of NT$105,451,644. <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=PCDM%2C112%2C%E6%99%BA%E9%87%8D%E9%99%84%E6%B0%91%2C1%2C20250624%2C2>
- Not established here: whether the scraped pages required a login (not determined from the passages read); the outcome on appeal (no appellate decision found).
- Related: 臺灣新北地方法院 112年度聲判字第65號刑事裁定 (2023-09-01) left in place the non-prosecution of two other co-founders for lack of proof that they knew the crawler's source. <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=PCDM%2C112%2C%E8%81%B2%E5%88%A4%2C65%2C20230901%2C1>

**(b) Acquittal: 發8網 building database.** **[court holding]** 智慧財產及商業法院 113年度刑智上易字第35號刑事判決 (2025-01-16), affirming 臺灣臺北地方法院 112年度智易字第27號 (2024-03-28). <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=IPCM%2C113%2C%E5%88%91%E6%99%BA%E4%B8%8A%E6%98%93%2C35%2C20250116%2C2> and <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPDM%2C112%2C%E6%99%BA%E6%98%93%2C27%2C20240328%2C1>

- Parties: prosecution of 北一資訊有限公司 and its representative; complainant operated a free public property-information website.
- What was taken: a self-written crawler copied 102,228 address and community-name records over about a week, for the defendant's research on mail-sorting automation for a client. Commercial context; not a competitor of the site.
- Held: not guilty. The database lacked originality, so no 編輯著作. On the computer-misuse articles the prosecution added on appeal: for 第358條, "被告是寫一個瀏覽器來模擬瀏覽 ... 檢察官亦未舉證被告曾有輸入告訴人帳號密碼，或破解告訴人電腦之保護措施之舉，是被告上開行為自與刑法第358條規定之構成要件有閒"; for 第359條, "告訴人設立上開網站，係提供任何人得以免費查詢、瀏覽全部的建物資料，被告雖有取得上開資料，亦難認該當該條所定之「無故取得」要件。是被告之行為亦不構成刑法第359條之罪。"
- The decision does not mention any usage terms on that site.

**(c) Acquittal: LiTV stream sources.** **[court holding]** 智慧財產及商業法院 112年度刑智上易字第29號刑事判決 (2024-10-09), cited above; 最高法院 114年度台非字第155號刑事判決 (2025-10-01) dismissed the extraordinary appeal. <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPSM%2C114%2C%E5%8F%B0%E9%9D%9E%2C155%2C20251001%2C1>

- A paying member used a program that logged in with his own account and fetched stream-source files for many channels around the clock. Charged under 第358條, 第360條 and 著作權法.
- Held: not guilty. Logging in with one's own account is not intrusion; the site "於案發時並未限制用戶同時取得數頻道之訊號源或使用之流量"; and "並未造成本案網站之電腦系統癱瘓或嚴重異常，亦未實際影響其他用戶觀看影音內容之品質", so no 第360條 interference. A 第359條 theory raised late was not tried.

**(d) Acquittal: train-ticket booking program.** **[court holding]** 臺灣高等法院花蓮分院 107年度上訴字第55號刑事判決 (2019-05-31), cited above.

- Travel-agency staff used automation tools against the Taiwan Railways group booking site; the log showed about 1,423 requests a minute from four addresses. Charged under 第360條 and 第361條.
- Held: not guilty. The railway's own witness said the site kept serving ("還是可以服務"), so interference with the equipment was not proved, and damage to the public was not proved.

**(e) None on CAPTCHA.** **[none found]** No decision was found applying 第358條 to a program that solves or bypasses an image CAPTCHA. The search hits for 驗證碼 were about one-time passwords and stolen accounts.

### What the sources do not say

- No decision found addresses a private, non-commercial individual reading a public page by program.
- No decision found treats `robots.txt`, or a footer copyright notice, as bearing on "無故". The one criminal decision that relied on site wording relied on formal usage rules that named automated access, together with competition, wholesale copying and resale.
- No decision found says how low a request rate must be to be safe; (c) and (d) say only that the rates there were not proved to interfere.

### Reading

- 第358條: the facts involve no account, no protective measure cracked and no vulnerability. On the text and on (b) and (c), this article does not reach them.
- 第360條: one request a minute for one clinic is far below the volumes that were held not to be interference in (c) and (d). The risk is not zero in principle, because the test is effect on the system, not a number.
- 第359條 is where the owner's position is weakest. The Supreme Court's definition of "無故" includes "違反所有人意思" and "逾越授權範圍", and in (a) a district court read published usage rules as the limit of authorisation. Against that, an appellate court in (b) held that taking data from a site open to everyone for free reading was not "無故取得". The two cases differ on facts that matter to the reader here (competitor, 331,524 records copied into a product for sale, explicit rule against automated querying, in (a); none of those in the facts). The researcher's reading is that the facts sit much closer to (b) than to (a), and also that fetching a page and keeping one number transiently is a weak fit for "取得 ... 移轉為自己所有" and for "致生損害". That is a reading. No court has ruled on it, (a) is a first-instance decision, and the Supreme Court's "致生損害" test is broad.
- Among the notices in the survey, the one closest to the rules relied on in (a) is the "online reading only; no storing, distributing or reproducing" wording. None of the notices recorded in the survey mentions automated access.
- 第361條 would raise the penalty by half if a public hospital's web server counts as "公務機關之電腦". Not resolved here; see section 7.

## 2. Copyright: 著作權法

### What the text says

**[statute text]** 著作權法, last amended 民國111年6月15日. <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=J0070017&flno=3> (change `flno`; `10-1`, `80-2` for 之 articles)

- 第3條第1項第5款: "重製：指以印刷、複印、錄音、錄影、攝影、筆錄或其他方法直接、間接、永久或暫時之重複製作。"
- 第3條第1項第4款: "公眾：指不特定人或特定之多數人。但家庭及其正常社交之多數人，不在此限。"
- 第7條第1項: "就資料之選擇及編排具有創作性者為編輯著作，以獨立之著作保護之。"
- 第9條第1項第3款: 不得為著作權之標的 includes "標語及通用之符號、名詞、公式、數表、表格、簿冊或時曆。" 第1款 excludes "憲法、法律、命令或公文".
- 第10條之1: "依本法取得之著作權，其保護僅及於該著作之表達，而不及於其所表達之思想、程序、製程、系統、操作方法、概念、原理、發現。"
- 第22條第3項 and 第4項: "前二項規定，於專為網路合法中繼性傳輸，或合法使用著作，屬技術操作過程中必要之過渡性、附帶性而不具獨立經濟意義之暫時性重製，不適用之。但電腦程式著作，不在此限。" "前項網路合法中繼性傳輸之暫時性重製情形，包括網路瀏覽、快速存取或其他為達成傳輸功能之電腦或機械本身技術上所不可避免之現象。"
- 第50條: "以中央或地方機關或公法人之名義公開發表之著作，在合理範圍內，得重製、公開播送或公開傳輸。"
- 第51條: "供個人或家庭為非營利之目的，在合理範圍內，得利用圖書館及非供公眾使用之機器重製已公開發表之著作。"
- 第65條第1項 and 第2項: "著作之合理使用，不構成著作財產權之侵害。" "著作之利用是否合於第四十四條至第六十三條所定之合理範圍或其他合理使用之情形，應審酌一切情狀，尤應注意下列事項，以為判斷之基準：一、利用之目的及性質，包括係為商業目的或非營利教育目的。二、著作之性質。三、所利用之質量及其在整個著作所占之比例。四、利用結果對著作潛在市場與現在價值之影響。"
- 第80條之2第1項: "著作權人所採取禁止或限制他人擅自進入著作之防盜拷措施，未經合法授權不得予以破解、破壞或以其他方法規避之。"
- 第91條 and 第100條: the database shows the 2022-05-04 amended text, whose effective date is still "由行政院定之". The in-force 第91條 (2019 version, read on the database's "舊法規內容" page) reads in part: "擅自以重製之方法侵害他人之著作財產權者，處三年以下有期徒刑、拘役，或科或併科新臺幣七十五萬元以下罰金。... 著作僅供個人參考或合理使用者，不構成著作權侵害。" <https://law.moj.gov.tw/LawClass/LawOldVer.aspx?pcode=J0070017>

### Agency interpretations

**[agency interpretation]** 經濟部智慧財產局, all read on the TIPO site:

- 電子郵件1140326 (2025-03-26): "如僅係將現成之客觀資訊，如數量、數據、單純之事實、名詞等予以羅列之報表(如貿易統計報表)，或係屬業界或一般日常習見且通用之表單(如學校行事曆、課程表、或交通業者公告之時刻表、票價表等)，均可能因內容不符合著作保護之要件或非屬著作權保護之標的". <https://www.tipo.gov.tw/tw/copyright/692-33512.html>
- 智著字第11310014290號 (2024-09-04), on transport timetables: "如僅係將時間、票價等資料以通用之表格羅列呈現，依前述說明，該等內容或不具原創性及創作性，或不得為著作權之標的，不受本法保護。" It adds that many government and state-run bodies post a 政府網站資料開放宣告 licensing protected content on their sites, and that privately published protected works still need permission or fair use. <https://www.tipo.gov.tw/tw/copyright/692-17213.html>
- 電子郵件1070814 (2018-08-14), on crawling financial quotes: price and trading information listed in a table "非屬著作權法保護之標的"; "惟如您以網路爬蟲所取得的資訊包括著作權法所稱之「著作｣ ... 則複製該等著作並於網路上提供，可能涉及「重製」及「公開傳輸」之行為，除有著作權法第44條至第65條所規定之合理使用情形外，應經著作財產權人同意或授權". <https://www.tipo.gov.tw/tw/copyright/692-15747.html>
- 電子郵件1151019 (2026-10-19), on a subtitle tool: "使用者透過網路觀看合法、有權存取之影片，因技術操作過程中必要之過渡性、附帶性而不具獨立經濟意義之暫時性重製，尚不涉及重製權之侵害"; a user who meets "「個人或家庭」、「非營利目的」及「合理範圍」" has room to rely on 第51條, in both a local and a cloud processing variant; and the developer "亦應注意雲端平台有無明文禁止「解析音訊」或「使用第三方外掛」，以避免民事違約之問題". <https://www.tipo.gov.tw/tw/copyright/692-99909.html>
- 電子郵件1140716 (2025-07-16): breaking a platform's 防盜拷措施 to download content "除可能違反Youtube服務條款外，亦有可能涉及侵害 ... 「重製權」，及違反本法第80條之2第2項". <https://www.tipo.gov.tw/tw/copyright/692-47239.html>
- Every letter ends by saying that copyright is a private right and disputes are for the courts on the facts.

**[none found]** No TIPO letter was found on hospital outpatient schedules or queue numbers. The search term 門診 returned one unrelated letter.

### Court holdings

- **[court holding]** 智慧財產及商業法院 113年度刑智上易字第35號 (cited in section 1): "著作權之保護端視其表達是否具有原創性，與「辛勤原則」、「汗水原則（sweat of brow）」無涉". The first instance added: "受著作權法保護之編輯著作保護範圍應僅限於資料之選擇及編排方式，不及於選編之內容".
- **[court holding]** 臺灣新北地方法院 111年度智訴字第8號 (cited in section 1) went the other way on its facts: a commercially edited statute-history database was a protected 編輯著作.
- **[court holding]** 智慧財產及商業法院 109年度民公上字第2號 (section 5): the listing site's page layout and listing phrases were not protected works, while four photographs were; copying them into the scraper's database and showing them in results was 重製 and 公開傳輸, and commercial use by a competitor was not fair use.

### What the sources do not say

- Whether a particular hospital's schedule page has enough original selection and arrangement to be a 編輯著作 is a case-by-case question no source answers.
- No source found says whether a rented cloud worker is a "非供公眾使用之機器" for 第51條. The 2026 TIPO letter treats a cloud variant as arguable; it does not decide it.
- No source found says a site notice can remove the statutory limits in 第44條 to 第65條. TIPO's letters point to a separate contract question (section 5).

### Reading

- A current queue number, a clinic time, a room number and a doctor's name are facts. Under 第10條之1, 第9條第1項第3款 and the TIPO timetable letters, they are not protected as such. This is the firmest point in the whole file.
- Fetching a page necessarily makes a temporary copy (第3條第1項第5款 counts temporary copies). If the page contains protected expression, the copy has to fall under 第22條第3項, 第51條 or 第65條. Non-commercial family use, a tiny portion, immediate discard and no market effect all point toward those provisions, but each is a "合理範圍" judgment for a court.
- A private message to a few family members that says the queue is near does not reproduce or publicly transmit a work; family is outside "公眾" by 第3條第1項第4款.
- The "禁止以任何形式儲存" wording, read as a copyright statement, cannot enlarge what copyright covers, but see section 5 for the contract question.

## 3. Personal data: 個人資料保護法

### What the text says

**[statute text]** 個人資料保護法, amended 民國114年11月11日; the database notes that the 2025 amendments (to 第41條, 第47條 to 第49條 and others) have an effective date "由行政院定之" and shows "最後生效日期：未定". The articles quoted here were not among those amended. <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=I0050021&flno=51>

- 第2條第1款: 個人資料 includes "自然人之姓名 ... 職業、病歷、醫療 ... 及其他得以直接或間接方式識別該個人之資料". 第8款: 非公務機關 means "前款以外之自然人、法人或其他團體".
- 第51條第1項: "有下列情形之一者，不適用本法規定：一、自然人為單純個人或家庭活動之目的，而蒐集、處理或利用個人資料。二、於公開場所或公開活動中所蒐集、處理或利用之未與其他個人資料結合之影音資料。"
- 第19條第1項: "非公務機關對個人資料之蒐集或處理，除第六條第一項所規定資料外，應有特定目的，並符合下列情形之一者：... 三、當事人自行公開或其他已合法公開之個人資料。... 七、個人資料取自於一般可得之來源。但當事人對該資料之禁止處理或利用，顯有更值得保護之重大利益者，不在此限。八、對當事人權益無侵害。" 第2項: "蒐集或處理者知悉或經當事人通知依前項第七款但書規定禁止對該資料之處理或利用時，應主動或依當事人之請求，刪除、停止處理或利用該個人資料。"
- 第20條第1項: "非公務機關對個人資料之利用，除第六條第一項所規定資料外，應於蒐集之特定目的必要範圍內為之。" followed by seven exceptions.
- 第6條第1項: "有關病歷、醫療、基因、性生活、健康檢查及犯罪前科之個人資料，不得蒐集、處理或利用。但有下列情形之一者，不在此限：..."
- 第5條: "個人資料之蒐集、處理或利用，應尊重當事人之權益，依誠實及信用方法為之，不得逾越特定目的之必要範圍，並應與蒐集之目的具有正當合理之關聯。"
- 施行細則 第28條: "本法第十九條第一項第七款所稱一般可得之來源，指透過大眾傳播、網際網路、新聞、雜誌、政府公報及其他一般人可得知悉或接觸而取得個人資料之管道。" <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=I0050022&flno=28>
- Enforcement, for reference: 第41條 (criminal; requires "意圖為自己或第三人不法之利益或損害他人之利益" and "足生損害於他人") and 第47條 (administrative fine of NT$50,000 to 500,000 for breach of 第19條 or 第20條第1項). The in-force wording was read on the old-version page. <https://law.moj.gov.tw/LawClass/LawOldVer.aspx?pcode=I0050021>

### Agency interpretations

Both read on laws.gov.taipei, not on the issuing agency's own site.

- **[agency interpretation]** 法務部 102年3月27日 法律字第10203502790號書函: "自然人為單純個人活動目的，而將其親友個人資料（例如：照片、影片或電話），於網路上分享予其他友人等利用行為，尚無本法之適用。惟上開行為若有侵害民眾人格權或隱私權者，受害人仍得根據民法第 18 條、第 184 條及第 195 條等規定，請求法院除去侵害或防止侵害及損害賠償". <https://laws.gov.taipei/Law/Interpretation/Content/FE257544>
- **[agency interpretation]** 國家發展委員會 108年5月17日 發法字第1080009012號函, on a private online genealogy site: it restates the legislative reason for 第51條第1項第1款 ("因屬私生活目的所為，與其職業或業務職掌無關，如納入個資法之適用，恐造成民眾之不便亦無必要，爰予以排除") and concludes that because "該網站係供不特定人瀏覽，且內容涉及族譜成員之工作地、配偶、子女、戶籍地址及連絡電話等詳細資料 ... 恐已逾越單純個人或家庭活動目的之必要範圍，而難認有個資法第 51 條之適用". <https://laws.gov.taipei/Law/Interpretation/Content/FE367127>

**[none found]** No interpretation was found on a private person collecting doctors' names from public clinic schedules, or on automated collection under 第51條第1項第1款.

### Reading

- A doctor's name on a public schedule is personal data (第2條第1款). A natural person helping the family attend a clinic is, on the text and the two letters, within "單純個人或家庭活動", so the Act does not apply. The 2019 letter marks the edge: making the data viewable by unspecified persons takes the activity out of the exemption. The facts keep it inside (a few invited family members, nothing public).
- If the exemption did not apply, 第19條第1項第7款 with 施行細則 第28條 covers data taken from the internet as a generally available source, subject to the data subject's overriding interest, and 第20條 confines use to the purpose.
- Patient data is a different matter. 病歷 and 醫療 data fall under 第6條. The facts say no patient identifier is used and only a clinic's current number is read; a bare number being called is not, by itself, data identifying a person. Any design that reads another patient's identifier, name or record would leave this analysis.
- The 第51條 exemption removes the Act, not civil liability for privacy harm (the 2013 letter says so).

## 4. 醫療機構網際網路資訊管理辦法 and 醫療法

### What the text says

**[statute text]** 醫療機構網際網路資訊管理辦法, eight articles, issued 2010-02-04, amended 2015-11-03 (第3條, 第8條 amended; 第5條 deleted). <https://law.moj.gov.tw/LawClass/LawAll.aspx?PCode=L0020165>

- 第1條: "本辦法依醫療法（以下稱本法）第八十五條第三項規定訂定之。"
- 第2條: "本辦法所稱醫療機構網際網路資訊（以下稱網路資訊），指醫療機構透過網際網路，提供之該機構醫療相關資訊。前項資訊之內容，除本法第八十五條第一項規定者外，得包括有關該醫療機構之一般資料及人員、設施、服務內容、預約服務、查詢或聯絡方式、醫療或健康知識等資訊。"
- 第3條: "醫療機構提供網路資訊，應將其網域名稱、網址或網路工具及網頁內主要可供點閱之項目，報所在地主管機關備查；異動時亦同。前項網路資訊內容，除其他醫事法令另有規定外，不得登載其他業者或非同一醫療體系之醫療機構資訊。第一項備查之方式，得以電子郵件為之。"
- 第4條: "前條網路資訊之首頁，應以明顯文字，聲明禁止任何網際網路服務業者轉錄其網路資訊之內容供人點閱。但以網路搜尋或超連結方式，進入醫療機構之網址（域）直接點閱者，不在此限。"
- 第6條: "網路資訊內容，應由醫療機構負責其正確性，不得有與事實不符或無法積極證明其為真實之內容。"
- 第7條: "網路資訊所載之醫療或健康知識，應標示製作或更新日期，並加註內容來源或主要科學文獻依據。"
- 第8條: effective dates.

**[statute text]** 醫療法 (last amended 民國115年9月23日). <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0020021&flno=85>

- 第85條第3項 (the enabling provision, inside the chapter on 醫療廣告): "醫療機構以網際網路提供之資訊，除有第一百零三條第二項各款所定情形外，不受第一項所定內容範圍之限制，其管理辦法由中央主管機關定之。"
- 第84條: "非醫療機構或醫師，不得為醫療廣告。" 第9條 defines 醫療廣告 as "利用傳播媒體或其他方法，宣傳醫療業務，以達招徠患者醫療為目的之行為". 第104條: "違反第八十四條規定為醫療廣告者，處新臺幣五萬元以上二十五萬元以下罰鍰。"
- 第103條第1項第1款 fines violations of a list that includes 第85條 and 第86條; 第2款 fines violations of regulations made under 第62條第2項 and 第93條第2項 only.
- 第115條: "本法所定之罰鍰，於私立醫療機構，處罰其負責醫師。本法所定之罰鍰，於醫療法人設立之醫療機構，處罰醫療法人。"

### What the sources say and do not say

- Every operative article of the regulation is addressed to the 醫療機構: it must report its site, must post the statement on its home page, must keep content accurate, must date its health information. 第4條 is a duty to post a statement. The regulation contains no article addressed to third parties and no penalty article.
- **[none found]** No article of 醫療法 was found that names a sanction for a third party who transcribes a hospital's web content, and none that names a sanction for breach of the regulation made under 第85條第3項 as such. The fine in 第103條第1項第1款 for violating 第85條 falls, by 第115條, on the responsible physician or the medical juridical person. A third party enters the Act's advertising rules only through 第84條 and 第104條, which concern non-institutions making 醫療廣告.
- **[none found]** No 衛生福利部 interpretation or court decision was found defining "網際網路服務業者" or "轉錄 ... 供人點閱" in 第4條.

### Reading

- The owner's position holds here on the text: 第4條 obliges the hospital to state something; it does not by itself prohibit anyone else from anything, and no sanction against a third party was found.
- On its wording, what the hospital must declare forbidden is an internet service operator transcribing the content "供人點閱", that is, republishing it for others to click and read, with search and hyperlink entry expressly excepted. Reading a page and sending a family member a private message with no hospital content, plus a link to the hospital's own page, is not transcription for others to browse, and linking is inside the proviso. Whether a one-person family tool is a "網際網路服務業者" at all is doubtful but undecided.
- What would move toward the concern behind this rule: showing hospital schedule or progress content on a page of one's own for others to view. A non-institution republishing clinic times and doctor lists to the public could also raise the separate 第84條 question of 醫療廣告. That is outside the facts.

## 5. Civil liability

### Text

**[statute text]** 民法 (<https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=B0000001&flno=184>):

- 第184條: "因故意或過失，不法侵害他人之權利者，負損害賠償責任。故意以背於善良風俗之方法，加損害於他人者亦同。違反保護他人之法律，致生損害於他人者，負賠償責任。但能證明其行為無過失者，不在此限。"
- 第153條第1項: "當事人互相表示意思一致者，無論其為明示或默示，契約即為成立。"
- 第161條第1項: "依習慣或依其事件之性質，承諾無須通知者，在相當時期內，有可認為承諾之事實時，其契約為成立。"

**[statute text]** 消費者保護法 第13條第1項, for standard terms between a business and a consumer: "企業經營者應向消費者明示定型化契約條款之內容；明示其內容顯有困難者，應以顯著之方式，公告其內容，並經消費者同意者，該條款即為契約之內容。" <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=J0170001&flno=13>

**[statute text]** 公平交易法 (<https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=J0150002&flno=25>):

- 第25條: "除本法另有規定者外，事業亦不得為其他足以影響交易秩序之欺罔或顯失公平之行為。"
- 第2條第1項: "本法所稱事業如下：一、公司。二、獨資或合夥之工商行號。三、其他提供商品或服務從事交易之人或團體。"
- 第29條 to 第31條 give injunction and damages against an 事業 that violates the Act; 第42條 gives the Commission power to fine an 事業.

**[agency interpretation]** 公平交易委員會對於公平交易法第二十五條案件之處理原則 第七點(二), as quoted by the court in 109年度民公上字第2號: 顯失公平 includes "榨取他人努力成果，如：... 抄襲他人投入相當努力建置之網站資料，混充為自身網站或資料庫之內容，藉以增加自身交易機會". 第五點, as quoted there: "單一個別非經常性之交易糾紛，原則上應尋求民事救濟，而不適用本條之規定". The guideline was not opened on the Commission's site.

### Scraping decisions

**(a) 591 v. 豬豬快租.** **[court holding]** 智慧財產及商業法院 109年度民公上字第2號民事判決 (2022-02-16), dismissing the appeal from 智慧財產法院 107年度民公訴字第8號. <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=IPCV%2C109%2C%E6%B0%91%E5%85%AC%E4%B8%8A%2C2%2C20220216%2C2>

- Parties: 數字科技股份有限公司 (591房屋交易網) against 豬豬科技 and its sole director, who wrote the app.
- What was scraped: rental listings, crawled into the defendant's own database and shown in its app; the Commission had found 86.13% of the app's listings came from 591.
- Commercial: yes. The court found the two competed for traffic and advertising revenue.
- Held: violation of 公平交易法 第25條 and tort under 民法 第184條第2項; injunction and NT$370,000 (NT$350,000 for unfair competition, NT$20,000 for four photographs). The court recorded as undisputed that 公平交易委員會 106年10月3日 公處字第106084號處分書 had found versions 1 and 2 of the app in violation.
- Site terms and `robots.txt`: the site's terms forbade unauthorised use and reproduction, it blocked the scraper's IP addresses, which the defendant "一再破解", and "被上訴人並於網站伺服器設置「robots.txt」檔，防止網路爬蟲行為". The court's use of these: "堪認上訴人無視被上訴人不願提供網站資料內容的意願，持續爬取被上訴人之591房屋網站資料之行為，造成被上訴人須不斷更新防堵機制，影響被上訴人網站之正常運作，減損及妨害被上訴人網站之經濟效能，及增加被上訴人之網站營運成本。" They were one factor in an overall assessment, not a ground of liability by themselves.
- Crawler as a tool: the court adopted the first instance's view that "上訴人所使用之網路爬蟲技術係屬中性之網路工具，並非係背於善良風俗之方法，故上訴人並未構成民法第184條第1項後段「故意以背於善良風俗之方法加損害於他人」之侵權行為".
- Who is an 事業: it also adopted the view that the company "始為受公平交易法規範之「事業」", and the individual director "並非公平交易法所指之「事業」", so the 第30條 claim against him failed; he was liable under 民法 第184條第2項 with 第28條 as the company's director.
- Search engines distinguished: general portals link to varied information and do not compete with the linked sites.

**(b) Real-estate agencies v. 屋比 / Ubee.** **[court holding]** Five decisions, still open.

- Parties: ten real-estate brokerage companies against 歐克斯科技股份有限公司 and two former representatives.
- What was done: a comparison site and app gathered listing information from the agencies' public sites and deep-linked to the listing pages; the operator charged brokers a membership fee to be contacted by users. Several plaintiffs' sites stated "未經同意，不得任意轉載使用".
- Commercial: yes.
- 智慧財產法院 106年度民公訴字第9號 (2018-01-09): claims dismissed; no violation of 第25條, 民法 第184條第1項後段 or trademark law. <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=IPCV%2C106%2C%E6%B0%91%E5%85%AC%E8%A8%B4%2C9%2C20180109%2C1>
- 智慧財產法院 107年度民公上字第1號 (2019-02-14): appeal dismissed. As the Supreme Court later summarised it, the appeal court noted the sites' no-reproduction statements and still found that the platform "並未實際轉載使用上訴人之網頁資料", and that it "可增加房屋物件資訊之透明度與流通性，促進房仲業間之競爭". <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=IPCV%2C107%2C%E6%B0%91%E5%85%AC%E4%B8%8A%2C1%2C20190214%2C1>
- 最高法院 109年度台上字第1756號 (2021-03-18): reversed and remanded. <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPSV%2C109%2C%E5%8F%B0%E4%B8%8A%2C1756%2C20210318%2C1>
- 智慧財產及商業法院 110年度民公上更(一)字第3號 (2022-10-27): found a 第25條 violation, enjoined use of the linked listings for the broker-referral function, and awarded NT$143,200 to each plaintiff. <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=IPCV%2C110%2C%E6%B0%91%E5%85%AC%E4%B8%8A%E6%9B%B4%28%E4%B8%80%29%2C3%2C20221027%2C1>
- 最高法院 112年度台上字第585號 (2026-01-15): reversed and remanded again. The court said: "倘事業之行為不具商業競爭倫理非難性，並無欺罔或顯失公平，或不足以影響交易秩序者，自無公平法第25條之適用", questioned whether the parties competed at all, and asked whether losing some deals "是否為其於網路公開房源資訊藉以招徠買方客源於市場競爭機制下所可能面臨之風險". <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPSV%2C112%2C%E5%8F%B0%E4%B8%8A%2C585%2C20260115%2C1>
- State on the research date: no final outcome.

**(c) Lending-site listings.** **[court holding]** 臺灣高等法院 109年度上字第1278號民事判決 (2021-05-11), affirming 臺灣新北地方法院 109年度訴字第771號. A lending-platform operator sued the sole proprietor of a rival lending site that displayed at least 582 borrower listings copied from the plaintiff's site (how they were copied was not established). Commercial, direct competitor. Held: violation of 第25條; damages measured at NT$89,628 by the cost of acquiring those listings. <https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPHV%2C109%2C%E4%B8%8A%2C1278%2C20210511%2C1>

**(d) 愛食記 v. 飢餓黑熊.** **[secondary source only]** A law-firm newsletter reports that 公平交易委員會 公處字第111070號 (September 2022) fined the operator of one restaurant-review app for scraping a competitor's compiled links and data. The disposition was not opened. <https://www.leeandli.com/TW/Newsletters/6954.htm>

**(e) Job banks and price-comparison sites.** **[none found]** The searches run (人力銀行 with 擷取 and 職缺; 比價 with 擷取 and 榨取他人努力成果) returned no scraping decision. That reflects those search terms only.

### Website terms as a contract

**[none found]** No decision was found holding that terms of use which a visitor never affirmatively accepted formed a contract, and none holding the opposite. The one search combining 爬蟲, 服務條款 and 契約 returned only the 591 decision, which treated the terms as evidence of the site's unwillingness and decided the case on unfair competition and tort, not contract. The Lawsnote criminal court treated usage rules as marking the "授權範圍" for "無故", again not as a contract. TIPO's 2025 and 2026 letters mention that breaching platform terms may raise "民事違約", without saying when terms bind.

### Reading

- 公平交易法 第25條 binds an "事業". On 第2條 and on the 591 holding that even the company's own director was not an 事業, a private person who offers no goods or services and trades with nobody does not look like one. No decision found tests that for a non-commercial hobby tool, so it is a reading.
- Every decision that imposed liability found competition, substitution of the plaintiff's service, and bulk incorporation of its data into the defendant's product. The facts have none of the three: the tool sends the owner to the hospital's page and tells the family to watch the on-site display.
- 民法 第184條第1項前段 needs unlawful infringement of a right plus damage; 第1項後段 needs intent to harm by means against good morals, and two courts called a crawler a neutral tool; 第2項 needs breach of a protective statute. On the facts the researcher sees no clear route to any of them, short of volume that actually burdens the server.
- Contract is the least settled civil question. 民法 第153條 allows tacit agreement, so it cannot be said that browse-only terms can never bind. For a visitor who clicks nothing and is shown nothing to accept, no source found says they do.

## 6. robots.txt and site notices

Stated plainly:

- **[none found]** No statute or regulation was found that mentions `robots.txt` or gives it legal effect. No statute or regulation was found that gives a footer notice, a copyright line or a "do not reproduce" line legal effect by itself. The one notice that originates in a regulation, the 第4條 sentence, is a statement hospitals are required to post (section 4).
- **[court holding]** A full-text search of 司法院裁判書系統 for "robots.txt" on 2026-11-17 returned six decisions. Two that were opened concern a website-development contract dispute in which `robots.txt` appears only as a technical issue (臺灣新北地方法院 112年度訴字第1477號; 臺灣高等法院 112年度抗字第587號). Three were judged from their captions only and not opened (臺灣高等法院 112年度抗字第610號 假處分; 臺灣臺南地方法院 104年度訴字第1903號 給付價金; 智慧財產法院 98年度行專訴字第126號 新型專利舉發). The only one in a scraping context is 109年度民公上字第2號, quoted in section 5.
- How such statements have actually been used:
  - As evidence of the operator's will. In the 591 case, terms, IP blocking and `robots.txt` together showed the scraper ignored the site's unwillingness and imposed defence costs; this went to "顯失公平" among many factors.
  - As the boundary of authorisation for "無故". In the Lawsnote case, written usage rules that named automated querying, which the defendants knew, were part of the finding under 刑法 第359條. The Supreme Court's general definition of "無故" includes "違反所有人意思" and "逾越授權範圍".
  - As not decisive. In the Ubee case two courts noted "未經同意，不得任意轉載使用" statements and still dismissed the claims; in the 發8網 case an open, free site meant no "無故取得".
- What a notice can still do: prove that the reader knew the operator's wishes, which matters to intent and to "無故"; define what the operator authorised; support an argument about contract; and in a civil case show that continued access was against a stated will. A notice addressed to everyone in a footer is weaker evidence of this than a refusal addressed to the reader, or a technical block, but no decision found measures that difference.
- Applied to the notices in the survey: plain "未經許可請勿轉載" lines and the 第4條 sentence concern reproduction and republication, which the facts do not involve. The "online reading only, no storing in any form" line is broader and is the one that could be argued to limit authorisation. The `robots.txt` that names AI crawler user agents and declares `ai-train=no` addresses crawlers that identify with those names and the use of content for model training; whether a given client falls under an entry is a question of fact, and no source found gives the file legal force either way. A client that hid its identity to evade a rule aimed at it would create the "knew and went around it" evidence that hurt the defendant in the 591 case.

## 7. Public hospitals

### What the text says

**[statute text]** 政府資訊公開法 (<https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=I0020026&flno=4>):

- 第4條第1項: "本法所稱政府機關，指中央、地方各級機關及其設立之實（試）驗、研究、文教、醫療及特種基金管理等機構。"
- 第3條 defines 政府資訊 as information a government agency makes or obtains within its functions, in any medium.
- 第5條: "政府資訊應依本法主動公開或應人民申請提供之。" 第6條: "與人民權益攸關之施政、措施及其他有關之政府資訊，以主動公開為原則，並應適時為之。"
- 第7條 lists ten categories that must be proactively published (laws, interpretive rules, organisation and contact details, administrative guidance, plans and statistics, budgets, petition results, procurement contracts, subsidies, meeting records). 第8條 lists publication methods, including "利用電信網路傳送或其他方式供公眾線上查詢". 第9條 gives nationals a right to request information.

**[agency interpretation]** 政府資料開放授權條款－第1版 (2015-07-27), read on data.gov.tw: it applies to "開放資料" that a "資料提供機關" (government bodies, state enterprises, public schools, administrative corporations) releases under the licence; it grants use "不限目的、時間及地域、非專屬、不可撤回、免授權金" including reproduction, public transmission and adaptation, with an attribution duty ("未盡顯名標示義務者，視為自始未取得開放資料之授權"). <https://data.gov.tw/license>

**[agency interpretation]** TIPO 智著字第11310014290號 (section 2) notes that many government and state-run bodies post a 政府網站資料開放宣告 on their sites, which licenses the protected content on the site without separate permission.

### What the sources do not say

- 第4條 brings government-established medical institutions inside the Act's definition of 政府機關. But clinic schedules and queue numbers are not in the 第7條 list, and the Act regulates what agencies must publish or provide. Nothing in the articles read addresses how the public may fetch published pages, and nothing in them prohibits or licenses automated reading.
- The open-data licence covers only what an agency has released under it. Whether a given hospital has done so is a fact about that hospital: the survey records such a declaration at 臺中榮總, alongside a restrictive footer on the same site, and records 新北市立聯合醫院 queue progress published as licensed open data with an API (a hospital outside the survey sample).
- **[none found]** No source was found on whether a public hospital's web server is a "公務機關之電腦" for 刑法 第361條. The 2003 legislative reason quoted in the 花蓮分院 decision says: "本條所稱公務機關，係指電腦處理個人資料保護法第三條所定之公務機關". That statute is now 個人資料保護法, whose 第2條第7款 reads "公務機關：指依法行使公權力之中央或地方機關或行政法人". Whether a public hospital providing clinical services fits that definition was not found addressed.

### Reading

- For government hospitals the law helps at the edges and changes nothing at the centre. It helps on copyright: 第50條 allows reasonable reproduction of works published in the name of a government body, and a site-wide open-data declaration, where one exists, licenses the protected content. It does not create a right to poll, and it does not displace the computer-misuse analysis in section 1.
- It also cuts the other way: if 第361條 applies, the same conduct against a public hospital's server carries a heavier penalty.
- Where an official open-data feed for queue progress exists, using it is a clearer footing than reading the web page, because the licence expressly grants the use.

## 8. What would change the answer

Each item names the source that makes it matter.

1. **Bypassing a login, a CAPTCHA or another access control.** 刑法 第358條 names "破解使用電腦之保護措施" and "輸入他人帳號密碼"; the 智慧財產及商業法院 gave "使用電腦程式解除帳號管理系統之限制" as its example. 著作權法 第80條之2 separately forbids circumventing access-control measures on works. No decision on image CAPTCHAs was found, so the exact reach is untested, but this is the clearest textual line in the chapter.
2. **Getting around a block aimed at you**, such as rotating addresses after an IP block or disguising the client to evade a rule. In the 591 case, repeatedly defeating blocking was held against the defendant.
3. **Request volume that degrades the service.** 刑法 第360條. The acquittals turned on the absence of proven impact on the system. The 591 court also counted the load and defence cost imposed on the site.
4. **Bulk copying and keeping the content**, as opposed to reading one clinic's row and discarding it. Scale and incorporation into one's own database were central in the Lawsnote, 591 and lending-site decisions, and "所利用之質量" is a 第65條 factor.
5. **Republishing content publicly**, on a page, app or public channel. That engages 公開傳輸 under 著作權法 for any protected content, is the very thing the 第4條 statement targets, takes personal data outside 個資法 第51條第1項第1款 according to the 2019 letter, and for a non-institution could raise 醫療法 第84條.
6. **Commercial use or offering the tool to the public.** That makes the operator an 事業 under 公平交易法 第2條, weighs against fair use under 第65條, removes "個人或家庭" under 著作權法 第51條 and 個資法 第51條, and supplied the damage element in every adverse decision.
7. **Continuing after an explicit refusal addressed to you.** "違反所有人意思" is within the Supreme Court's definition of "無故". No decision was found on a refusal sent to a non-commercial reader, but after one, the argument that access was authorised by the page being public is much weaker.
8. **Collecting patient data.** 個資法 第6條 for 病歷 and 醫療 data; using someone else's identifier to query a page would also be acting outside what the operator offers that person.
9. **Probing undocumented endpoints or exploiting a flaw.** 刑法 第358條 "利用電腦系統之漏洞".
10. **A site that publishes explicit rules against automated access.** After the Lawsnote decision this is a real change in risk under 第359條, even though that case also had competition and resale. None of the notices recorded in the survey does this.

## Lists

### (a) Acts the sources clearly prohibit

- Entering another's computer by using someone else's account and password, cracking a protective measure, or exploiting a vulnerability, without cause (刑法 第358條, statute text).
- Interfering with another's computer by program so as to cause damage (刑法 第360條, statute text; courts require a significant effect on normal operation).
- Taking, deleting or altering another's electromagnetic records without cause and causing damage (刑法 第359條, statute text). Applied by a district court to a competitor's bulk crawling against published usage rules, for resale (新北地院 111年度智訴字第8號, first instance).
- Reproducing or publicly transmitting protected works without permission or fair use (著作權法 第22條, 第26條之1, 第91條, 第92條, statute text; applied to scraped photographs in 109年度民公上字第2號).
- Circumventing an access-control measure protecting a work (著作權法 第80條之2, statute text).
- For an 事業: copying a competitor's site data into one's own product so as to affect trading order (公平交易法 第25條; 109年度民公上字第2號; 臺灣高等法院 109年度上字第1278號). The Supreme Court's 2026 remand in the Ubee case shows the limits of this are still contested.
- Collecting or using 病歷 or 醫療 personal data outside the listed exceptions (個資法 第6條, statute text).
- For a medical institution: failing its own duties under 醫療機構網際網路資訊管理辦法. This binds hospitals, not readers.

### (b) Acts where the sources show no prohibition on the facts, with the uncertainty

- **Reading a public page with a program, with no login, no CAPTCHA and no flaw exploited.** Outside 第358條 on its text and on two appellate holdings. Uncertainty: low.
- **About one request a minute for one clinic.** Far below what was held not to be interference under 第360條. Uncertainty: low, as long as the site is not in fact burdened.
- **Obtaining the page content at all, under 第359條.** One appellate court held that taking data from a free public site was not "無故取得"; one district court convicted where usage rules banned automation and the taker was a reselling competitor. Uncertainty: real. It turns on what the particular site says, on whether a transient read is "取得", and on "致生損害", and no decision covers a private reader.
- **Using the facts read (queue number, clinic time, room, doctor name).** Not protected by copyright as facts (第10條之1, 第9條第1項第3款, TIPO letters). Uncertainty: low for the facts themselves; a schedule page as a whole could still be a protected compilation, in which case the transient copy relies on 第22條第3項, 第51條 or 第65條, each a court judgment.
- **Handling doctors' names for a family purpose.** Outside 個資法 by 第51條第1項第1款, and otherwise within 第19條第1項第7款. Uncertainty: low while nothing is made viewable to unspecified persons; no interpretation found on automated collection.
- **The 第4條 "no transcription" sentence.** A duty on hospitals; it describes republication by internet service operators and excepts search and hyperlinks. Uncertainty: low for reading and private messaging; the terms are undefined by any source found.
- **公平交易法 第25條.** Applies to an 事業. A non-commercial private person does not appear to be one. Uncertainty: moderate, because no decision found tests it for a hobby tool.
- **robots.txt and footer notices.** No source gives them legal force by themselves. Uncertainty: they remain usable as evidence of the operator's will, and an explicit rule against automated access would raise the 第359條 risk.

### (c) Open questions for a lawyer

1. After the Lawsnote conviction, how would a court treat a non-commercial reader of a public page that carries a restrictive notice, under "無故" and "逾越授權範圍" in 刑法 第359條? Does it matter that the notice speaks of reproduction and storage, not of automated access?
2. Is fetching a page and keeping one number transiently "取得 ... 電磁紀錄" in the sense of "移轉為自己所有", and can "致生損害" be met when nothing is kept, republished or sold?
3. What became of the Lawsnote case on appeal, and does the appellate court confirm or narrow the use of site usage rules for "無故"?
4. Do browse-only website terms bind a visitor who accepts nothing, under 民法 第153條 and 第161條, and does 消費者保護法 第13條 or the rules on standard terms apply when the visitor is not a customer of the site?
5. Is a public hospital's web server a "公務機關之電腦" under 刑法 第361條?
6. Does the "online reading only; no storing, distributing or reproducing in any form" notice have any effect beyond what copyright law already provides, and can it limit 第51條 or 第65條?
7. Is a rented cloud worker a "非供公眾使用之機器" under 著作權法 第51條, and does running on a server change the "個人或家庭" characterisation under either statute?
8. Does a `robots.txt` entry naming AI crawler user agents, with `ai-train=no`, have any bearing on a client that is not an AI training crawler, and what is the consequence of the client's choice of user-agent string?
9. Would the answer differ for a hospital that has posted a 政府網站資料開放宣告, and should an official open-data feed be preferred wherever one exists?
10. What is the right response if a hospital objects: does stopping at once remove the exposure, and is there any duty to ask permission first?
11. Since 第358條 to 第360條 are prosecuted only on complaint, is asking each hospital for permission, or notifying it, advisable before any automated reading starts?
