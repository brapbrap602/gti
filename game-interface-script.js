// game-interface-script.js

document.addEventListener("DOMContentLoaded", function () {
  // Function to check if a line contains 15 or more consecutive dashes
  function isDashDelimiter(text) {
    const trimmedText = text.trim();
    // Check for 15 or more consecutive dash characters (various dash types)
    const dashPattern = /[-—–_]{15,}/;
    return dashPattern.test(trimmedText);
  }

  // Function to check if an element is a chapter marker
  function isChapterMarker(element) {
    return (
      element &&
      (element.classList.contains("calibre2") ||
        element.classList.contains("calibre"))
    );
  }

  // PASS 1: First, add missing delimiters to make all chapters have even delimiter counts
  function addMissingDelimiters() {
    const allElements = document.querySelectorAll("*");
    let chapterDelimiters = [];

    function processChapterForDelimiters() {
      // If odd number of delimiters, add a matching delimiter after the second-to-last one
      if (chapterDelimiters.length % 2 === 1 && chapterDelimiters.length > 0) {
        console.log(
          `Chapter has odd number of delimiters (${chapterDelimiters.length}). Adding matching delimiter.`
        );

        // Find the second-to-last delimiter (index = length - 2)
        const secondToLastIndex = chapterDelimiters.length - 2;
        if (secondToLastIndex >= 0) {
          const secondToLastDelimiter = chapterDelimiters[secondToLastIndex];

          // Create new delimiter paragraph
          const newDelimiter = document.createElement("p");
          newDelimiter.className = "calibre5";
          newDelimiter.textContent = "——————————————————————";

          // Insert it right after the second-to-last delimiter
          if (secondToLastDelimiter.nextSibling) {
            secondToLastDelimiter.parentNode.insertBefore(
              newDelimiter,
              secondToLastDelimiter.nextSibling
            );
          } else {
            secondToLastDelimiter.parentNode.appendChild(newDelimiter);
          }

          console.log(
            "Added matching delimiter after second-to-last delimiter"
          );
        }
      }
      chapterDelimiters = [];
    }

    for (let i = 0; i < allElements.length; i++) {
      const element = allElements[i];

      // Check if this is a chapter marker - process previous chapter
      if (isChapterMarker(element)) {
        processChapterForDelimiters();
        continue;
      }

      // Only check p.calibre5 elements for delimiters
      if (element.matches && element.matches("p.calibre5")) {
        const trimmedText = element.textContent.trim();
        if (isDashDelimiter(trimmedText)) {
          chapterDelimiters.push(element);
        }
      }
    }

    // Process the final chapter
    processChapterForDelimiters();
  }

  // PASS 2: Now process all interface blocks (including newly added delimiters)
  function processInterfaceBlocks() {
    const allElements = document.querySelectorAll("*");
    let currentInterfaceParagraphs = [];
    let inInterfaceBlock = false;
    let firstParagraphOfBlock = null;

    function processChapterEnd() {
      // Process any open block
      if (inInterfaceBlock && currentInterfaceParagraphs.length > 0) {
        processBlock(currentInterfaceParagraphs, firstParagraphOfBlock);
      }

      // Reset state for new chapter
      inInterfaceBlock = false;
      currentInterfaceParagraphs = [];
      firstParagraphOfBlock = null;
    }

    for (let i = 0; i < allElements.length; i++) {
      const element = allElements[i];

      // Check if this is a chapter marker - process previous chapter and reset
      if (isChapterMarker(element)) {
        processChapterEnd();
        continue;
      }

      // Only process p.calibre5 elements for interface blocks
      if (!element.matches("p.calibre5")) {
        continue;
      }

      const p = element;
      const trimmedText = p.textContent.trim();

      if (isDashDelimiter(trimmedText)) {
        if (inInterfaceBlock && currentInterfaceParagraphs.length > 0) {
          // This is a closing delimiter - process the current block
          currentInterfaceParagraphs.push(p);
          processBlock(currentInterfaceParagraphs, firstParagraphOfBlock);
          inInterfaceBlock = false;
          currentInterfaceParagraphs = [];
          firstParagraphOfBlock = null;
        } else {
          // This is an opening delimiter - start a new block
          inInterfaceBlock = true;
          firstParagraphOfBlock = p;
          currentInterfaceParagraphs = [p];
        }
      } else if (inInterfaceBlock) {
        currentInterfaceParagraphs.push(p);
      }
    }

    // Handle case where we're still in a block at the end
    if (inInterfaceBlock && currentInterfaceParagraphs.length > 0) {
      processBlock(currentInterfaceParagraphs, firstParagraphOfBlock);
    }
  }

  // Execute both passes
  addMissingDelimiters();
  processInterfaceBlocks();

  function processBlock(nodes, firstNode) {
    if (!firstNode || nodes.length === 0) {
      return;
    }

    const parent = firstNode.parentNode;
    if (!parent) {
      console.warn(
        "Skipping block processing: firstNode has no parent.",
        firstNode
      );
      return;
    }

    const interfaceDiv = document.createElement("div");
    interfaceDiv.classList.add("game-interface");

    const originalNextSibling = firstNode.nextSibling;
    const fragment = document.createDocumentFragment();

    nodes.forEach((node) => {
      if (node.parentNode === parent) {
        let rawText = node.textContent;

        // Step 1: Clean line-by-line whitespace
        // This removes leading/trailing whitespace from each line of text within the paragraph,
        // ensuring consistent left alignment regardless of source HTML indentation.
        let cleanedText = rawText
          .split("\n")
          .map((line) => line.trim())
          .filter((line) => line.length > 0)
          .join("\n");

        let finalContent = cleanedText; // Default to original cleaned text

        // Step 2: Check for and apply key-value styling (only if it's not a delimiter line)
        if (!isDashDelimiter(cleanedText)) {
          const colonIndex = cleanedText.indexOf(":");

          if (colonIndex !== -1) {
            const key = cleanedText.substring(0, colonIndex + 1); // "Key:"
            const value = cleanedText.substring(colonIndex + 1); // " Value"

            // If there's content after the colon, treat as key-value pair
            // We check value.trim().length > 0 to differentiate "Key:Value" from "Key:"
            if (value.trim().length > 0) {
              finalContent = `<span class="interface-key">${key}</span><span class="interface-value">${value}</span>`;
            } else {
              // Case like "Abilities:" where there's no explicit value following the colon
              finalContent = `<span class="interface-key">${key}</span>`;
            }
          }
          // If no colon, finalContent remains cleanedText (e.g., "You have been injected with Valkyrie!")
        }

        // Step 3: Apply content to the node
        if (isDashDelimiter(cleanedText)) {
          node.classList.add("game-interface-delimiter");
          node.textContent = cleanedText; // For delimiters, keep textContent and hide via CSS
        } else {
          node.innerHTML = finalContent; // For content, use innerHTML (might contain spans)
        }

        fragment.appendChild(node);
      }
    });

    interfaceDiv.appendChild(fragment);
    parent.insertBefore(interfaceDiv, originalNextSibling);
  }
});
