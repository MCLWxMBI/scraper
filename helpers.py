"""Reusable helpers for rendering websites and extracting readable text."""

import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import pdfplumber
from bs4 import BeautifulSoup
from playwright.sync_api import Browser, Page


@dataclass(frozen=True)
class Source:
    name: str
    url: str


VEWH_SOURCE_NAME = "Victorian Environmental Water Holder"
SARC_SOURCE_NAME = (
    "Scrutiny of Acts and Regulations Committee – environment filter"
)
JOINT_TREATIES_SOURCE_NAME = "Joint Treaties – environment-related only"
PDF_SOURCE_NAMES = frozenset(
    {VEWH_SOURCE_NAME, SARC_SOURCE_NAME, JOINT_TREATIES_SOURCE_NAME}
)


SOURCES = (
    Source("Parliament of Victoria – inquiries", "https://www.parliament.vic.gov.au/apartmentrenewables"),
    Source("Melbourne Water", "https://letstalk.melbournewater.com.au/psp"),
    Source("Greater Western Water", "https://www.gww.com.au/faults-works/upgrades-projects/planned-works-projects/romsey-water-filtration-plant"),
    Source("South East Water", "https://southeastwater.com.au/faults-and-works/works/projects/aquarevo/welcome-to-aquarevo/project/"),
    Source("Yarra Valley Water", "https://engage.yvw.com.au/projects"),
    Source("Barwon Water", "https://www.barwonwater.vic.gov.au/about-us/news-and-events/news/major-water-storage-site-to-double-in-capacity"),
    Source("Coliban Water", "https://connect.coliban.com.au/PS28"),
    Source("East Gippsland Water", "https://egwater.vic.gov.au/community/news/share-your-thoughts-on-our-future-services"),
    Source("Goulburn Valley Water", "https://watermatters.gvwater.vic.gov.au/shepparton-clear-water-storage-tank"),
    Source("Gippsland Water", "https://www.gippswater.com.au/outages-works-and-projects/major-projects/current-major-projects/new-treated-water-storage-traralgon"),
    Source("Grampians Wimmera Mallee Water", "https://gwmwater.org.au/building-and-development/projects/current-projects/east-grampians-rural-pipeline/"),
    Source("Lower Murray Water", "https://yoursay.lmw.vic.gov.au/price-submission-2028-2033"),
    Source("North East Water", "https://haveyoursay.newater.com.au/projects"),
    Source("South Gippsland Water", "https://www.sgwater.com.au/news/wosup-wonthaggi/"),
    Source("Wannon Water", "https://engage.wannonwater.com.au/share-your-thoughts"),
    Source("Western Port Water", "https://www.westernportwater.com.au/our-community/projects/current-projects/nextgenerationupgrade/"),
    Source("Southern Rural Water", "https://www.srw.com.au/initiatives/projects/avon-valley-water-security-project"),
    Source("Goulburn-Murray Water", "https://yoursay.gmwater.com.au/price-plan-2028"),
    Source("Essential Services Commission", "https://www.esc.vic.gov.au/current-consultations"),
    Source("Victorian Auditor-General's Office", "https://www.audit.vic.gov.au/annual-plan"),
    Source("Commissioner for Environmental Sustainability Victoria", "https://www.ces.vic.gov.au/news/celebrate-national-science-week-2026"),
    Source("Vic Catchments", "https://viccatchments.com.au/priority-projects/"),
    Source(VEWH_SOURCE_NAME, "https://www.vewh.vic.gov.au/planning-and-reporting/seasonal-watering-plan"),
    Source("Engage Victoria", "https://www.vic.gov.au/notice-preparation-regulatory-impact-statement-labour-hire-licensing-amendment-regulations-2026"),
    Source("Department of Industry, Science and Resources", "https://consult.industry.gov.au/horizon-europe-implementation"),
    Source("Productivity Commission", "https://www.pc.gov.au/inquiries-and-research/gst-reforms/"),
    Source("Climate Change Authority", "https://consult.climatechangeauthority.gov.au/2026-apa-consultation-paper"),
    Source("Australian Energy Market Commission", "https://www.aemc.gov.au/market-reviews-advice/electricity-network-regulation-review-package-2"),
    Source("Department of Climate Change, Energy, the Environment and Water", "https://consult.dcceew.gov.au/australia-singapore-transboundary-carbon-capture-and-sequestration-bilateral-instrument"),
    Source("Clean Energy Regulator", "https://cer.gov.au/news-and-media/public-consultations"),
    Source("Department of Infrastructure, Transport, Regional Development, Communications, Sport and the Arts", "https://www.infrastructure.gov.au/department/media/news/consultation-opens-new-aviation-disability-standards"),
    Source("Legislative Assembly Environment and Planning Committee", "https://www.parliament.vic.gov.au/apartmentrenewables"),
    Source("Legislative Council Environment and Planning Committee", "https://www.parliament.vic.gov.au/2026firesinquiry"),
    Source(SARC_SOURCE_NAME, "https://www.legislation.vic.gov.au/bills/domestic-gas-choice-repeal-gas-appliance-ban-bill-2026"),
    Source("Senate Environment and Communications", "https://www.aph.gov.au/Parliamentary_Business/Committees/Senate/Environment_and_Communications/AIdatacentres48P"),
    Source("Senate Rural and Regional Affairs and Transport", "https://www.aph.gov.au/Parliamentary_Business/Committees/Senate/Rural_and_Regional_Affairs_and_Transport/"),
    Source("House Climate Change, Energy, Environment and Water", "https://www.aph.gov.au/Parliamentary_Business/Committees/House/Climate_Change_Energy_Environment_and_Water/Solarpanelrecycling"),
    Source("House Industry, Innovation and Science", "https://www.aph.gov.au/Parliamentary_Business/Committees/House/Industry_Innovation_and_Science/AustralianTyreIndustry"),
    Source("House Regional Development, Infrastructure and Transport", "https://www.aph.gov.au/Parliamentary_Business/Committees/House/Regional_Development_Infrastructure_and_Transport/LocalGovernmentFunding"),
    Source("House Primary Industries", "https://www.aph.gov.au/Parliamentary_Business/Committees/House/Primary_Industries/CriticalMinerals"),
    Source("Joint Aboriginal and Torres Strait Islander Affairs", "https://www.aph.gov.au/Parliamentary_Business/Committees/Joint/Aboriginal_and_Torres_Strait_Islander_Affairs/Responsestoracism"),
    Source(JOINT_TREATIES_SOURCE_NAME, "https://www.aph.gov.au/Parliamentary_Business/Committees/Joint/Treaties/2025CITESAmendments/Treaty_being_considered"),
    Source("Joint Northern Australia", "https://www.aph.gov.au/Parliamentary_Business/Committees/Joint/Northern_Australia/Industries"),
)


STABLE_CONTENT_SCRIPT = """
({ minimumCharacters, quietMilliseconds, timeoutMilliseconds }) =>
  new Promise((resolve, reject) => {
    const selectors = ["main", "[role='main']", "article", "#app", "body"];
    const target = selectors.map((selector) => document.querySelector(selector))
      .find((element) => element !== null);
    if (!target) {
      reject(new Error("No page content root was found"));
      return;
    }

    const loadingPlaceholders = [
      "loading", "slow connection", "try refresh", "please wait",
      "enable javascript",
    ];
    let quietTimer;
    let timeoutTimer;
    let lastText = "";
    const normalizedText = () =>
      (target.innerText || "").replace(/\\s+/g, " ").trim();
    const isMeaningful = (text) => {
      if (text.length < minimumCharacters) return false;
      const lowerText = text.toLowerCase();
      return !loadingPlaceholders.some(
        (placeholder) => lowerText === placeholder ||
          (lowerText.length < 500 && lowerText.includes(placeholder)),
      );
    };
    const cleanup = () => {
      observer.disconnect();
      clearTimeout(quietTimer);
      clearTimeout(timeoutTimer);
    };
    const checkContent = () => {
      clearTimeout(quietTimer);
      lastText = normalizedText();
      if (!isMeaningful(lastText)) return;
      quietTimer = setTimeout(() => {
        const currentText = normalizedText();
        if (currentText === lastText && isMeaningful(currentText)) {
          cleanup();
          resolve(true);
        }
      }, quietMilliseconds);
    };
    const observer = new MutationObserver(checkContent);
    observer.observe(target, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: false,
    });
    timeoutTimer = setTimeout(() => {
      cleanup();
      const preview = lastText.slice(0, 160);
      reject(new Error(
        `Page content did not stabilize within ${timeoutMilliseconds}ms; ` +
        `last text length=${lastText.length}; preview=${JSON.stringify(preview)}`,
      ));
    }, timeoutMilliseconds);
    checkContent();
  })
"""


def fetch_rendered_html(page: Page, url: str) -> str:
    """Load a URL in an existing browser page and return its rendered DOM."""
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_function(
        "document.body && document.body.innerText.trim().length > 0",
        timeout=30_000,
    )
    return page.content()


def wait_for_stable_page_content(
    page: Page,
    minimum_characters: int = 200,
    quiet_milliseconds: int = 750,
    timeout_milliseconds: int = 30_000,
) -> None:
    """Wait until meaningful page text stops receiving relevant DOM mutations."""
    page.evaluate(
        STABLE_CONTENT_SCRIPT,
        {
            "minimumCharacters": minimum_characters,
            "quietMilliseconds": quiet_milliseconds,
            "timeoutMilliseconds": timeout_milliseconds,
        },
    )


def extract_page_text(html: str) -> str:
    """Extract compact, human-readable content from rendered HTML."""
    soup = BeautifulSoup(html, "html.parser")
    non_content_tags = (
        "head", "script", "style", "noscript", "template", "svg", "nav",
        "header", "footer", "aside", "input", "button", "select", "textarea",
        "dialog",
    )
    for element in soup.find_all(non_content_tags):
        element.decompose()

    block_tags = (
        "address", "blockquote", "br", "dd", "dt", "figcaption", "h1", "h2",
        "h3", "h4", "h5", "h6", "li", "p", "pre", "td", "th",
    )
    for element in soup.find_all(block_tags):
        element.append("\n")

    lines = (" ".join(line.split()) for line in soup.get_text(" ").splitlines())
    return "\n".join(line for line in lines if line)


def normalized_label(value: str) -> str:
    """Normalize human-readable labels for resilient source-specific matching."""
    return " ".join(value.split()).casefold()


def is_pdf_link(href: str | None) -> bool:
    return bool(href and href.casefold().split("?", 1)[0].endswith(".pdf"))


def extract_pdf_text(page: Page, pdf_url: str) -> str:
    """Download a PDF through Playwright and return normalized embedded text."""
    absolute_url = urljoin(page.url, pdf_url)
    response = page.context.request.get(absolute_url, timeout=30_000)
    if not response.ok:
        raise ValueError(
            f"PDF download failed with HTTP {response.status} "
            f"{response.status_text}: {absolute_url}"
        )

    try:
        with pdfplumber.open(BytesIO(response.body())) as pdf:
            extracted_pages = [pdf_page.extract_text() or "" for pdf_page in pdf.pages]
    except Exception as exc:
        raise ValueError(f"Could not parse PDF {absolute_url}: {exc}") from exc

    lines = (
        " ".join(line.split())
        for page_text in extracted_pages
        for line in page_text.splitlines()
    )
    return "\n".join(line for line in lines if line)


def extract_victorian_sarc_text(page: Page, rendered_html: str) -> str:
    """Extract the Victorian SARC Introduction print – Bill PDF text."""
    soup = BeautifulSoup(rendered_html, "html.parser")
    target_label = normalized_label("Introduction print – Bill")
    heading = next(
        (
            candidate
            for candidate in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
            if normalized_label(candidate.get_text(" ", strip=True)) == target_label
        ),
        None,
    )
    if heading is None:
        raise ValueError("Victorian SARC: 'Introduction print – Bill' panel not found")

    panel = heading.find_parent(
        "div", class_="tide-bill-intro__section-document"
    ) or heading.parent
    pdf_anchor = next(
        (
            anchor
            for anchor in panel.find_all("a", href=True)
            if is_pdf_link(anchor.get("href"))
        ),
        None,
    )
    if pdf_anchor is None:
        raise ValueError(
            "Victorian SARC: PDF link not found in 'Introduction print – Bill' panel"
        )
    return extract_pdf_text(page, pdf_anchor["href"])


def extract_vewh_text(page: Page, rendered_html: str) -> str:
    """Extract the VEWH Section 1 Introduction PDF text."""
    soup = BeautifulSoup(rendered_html, "html.parser")
    target_label = normalized_label("Section 1 Introduction")
    pdf_anchor = next(
        (
            anchor
            for anchor in soup.find_all("a", href=True)
            if is_pdf_link(anchor.get("href"))
            and target_label
            in {
                normalized_label(anchor.get("title", "")),
                normalized_label(anchor.get_text(" ", strip=True)),
            }
        ),
        None,
    )
    if pdf_anchor is None:
        raise ValueError("VEWH: 'Section 1 Introduction' PDF link not found")
    return extract_pdf_text(page, pdf_anchor["href"])


def extract_joint_treaties_text(page: Page, rendered_html: str) -> str:
    """Extract the Joint Treaties National Interest Analysis PDF text."""
    soup = BeautifulSoup(rendered_html, "html.parser")
    target_label = normalized_label("National Interest Analysis")
    paragraph = next(
        (
            candidate
            for candidate in soup.find_all("p")
            if normalized_label(candidate.get_text(" ", strip=True)).startswith(
                target_label
            )
        ),
        None,
    )
    if paragraph is None:
        raise ValueError("Joint Treaties: 'National Interest Analysis' paragraph not found")

    pdf_anchor = next(
        (
            anchor
            for anchor in paragraph.find_all("a", href=True)
            if is_pdf_link(anchor.get("href"))
        ),
        None,
    )
    if pdf_anchor is None:
        raise ValueError(
            "Joint Treaties: National Interest Analysis PDF link not found"
        )
    return extract_pdf_text(page, pdf_anchor["href"])


def process_single_source(source: Source, browser: Browser) -> str:
    """Render one source, select its extraction strategy, and return text."""
    page = browser.new_page()
    try:
        fetch_rendered_html(page, source.url)
        wait_for_stable_page_content(page)
        rendered_html = page.content()
        if source.name == VEWH_SOURCE_NAME:
            return extract_vewh_text(page, rendered_html)
        if source.name == SARC_SOURCE_NAME:
            return extract_victorian_sarc_text(page, rendered_html)
        if source.name == JOINT_TREATIES_SOURCE_NAME:
            return extract_joint_treaties_text(page, rendered_html)
        return extract_page_text(rendered_html)
    finally:
        page.close()
