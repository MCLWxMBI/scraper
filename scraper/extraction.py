"""HTML/PDF extraction utilities for rendering websites and extracting readable text."""

import re
import unicodedata
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import pdfplumber
from bs4 import BeautifulSoup
from playwright.sync_api import Browser, Page


from scraper.models import Source


VEWH_SOURCE_NAME = "Victorian Environmental Water Holder"
SARC_SOURCE_NAME = (
    "Scrutiny of Acts and Regulations Committee – environment filter"
)
JOINT_TREATIES_SOURCE_NAME = "Joint Treaties – environment-related only"
PDF_SOURCE_NAMES = frozenset(
    {VEWH_SOURCE_NAME, SARC_SOURCE_NAME, JOINT_TREATIES_SOURCE_NAME}
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
    # Engagement platforms put substantive timelines/FAQs in complementary
    # sidebars. Remove identified account/legal UI instead of every aside,
    # dialog, hidden panel or collapsed tab.
    account_modal_ids = (
        'privacyPolicyModal', 'termsOfUseModal', 'loginModal', 'resetPasswordModal',
        'signUpModal', 'signUpConfirmModal', 'userDetailsModal', 'followCTAModal',
        'signupCTAModal',
    )
    selector = ', '.join(f'#{name}' for name in account_modal_ids) + ', [role="navigation"]'
    for element in soup.select(selector):
        if element.parent is not None:
            element.decompose()
    non_content_tags = (
        "head", "script", "style", "noscript", "template", "svg", "nav",
        "header", "footer", "input", "button", "select", "textarea",
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
