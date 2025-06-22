// game-interface-script.js

document.addEventListener('DOMContentLoaded', function() {
    const startDelimiter = '_____________________';
    const endDelimiter = '¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯';

    const allParagraphs = document.querySelectorAll('p.calibre5');

    let currentInterfaceParagraphs = [];
    let inInterfaceBlock = false;
    let firstParagraphOfBlock = null;

    for (let i = 0; i < allParagraphs.length; i++) {
        const p = allParagraphs[i];
        const trimmedText = p.textContent.trim();

        if (trimmedText === startDelimiter) {
            if (inInterfaceBlock && currentInterfaceParagraphs.length > 0) {
                processBlock(currentInterfaceParagraphs, firstParagraphOfBlock);
            }
            inInterfaceBlock = true;
            firstParagraphOfBlock = p;
            currentInterfaceParagraphs = [p];
        } else if (trimmedText === endDelimiter) {
            if (inInterfaceBlock) {
                currentInterfaceParagraphs.push(p);
                processBlock(currentInterfaceParagraphs, firstParagraphOfBlock);
                inInterfaceBlock = false;
                currentInterfaceParagraphs = [];
                firstParagraphOfBlock = null;
            }
        } else if (inInterfaceBlock) {
            currentInterfaceParagraphs.push(p);
        }
    }

    if (inInterfaceBlock && currentInterfaceParagraphs.length > 0) {
        processBlock(currentInterfaceParagraphs, firstParagraphOfBlock);
    }

    function processBlock(nodes, firstNode) {
        if (!firstNode || nodes.length === 0) {
            return;
        }

        const parent = firstNode.parentNode;
        if (!parent) {
            console.warn("Skipping block processing: firstNode has no parent.", firstNode);
            return;
        }

        const interfaceDiv = document.createElement('div');
        interfaceDiv.classList.add('game-interface');

        const originalNextSibling = firstNode.nextSibling;
        const fragment = document.createDocumentFragment();

        nodes.forEach(node => {
            if (node.parentNode === parent) {
                let rawText = node.textContent;

                // Step 1: Clean line-by-line whitespace
                // This removes leading/trailing whitespace from each line of text within the paragraph,
                // ensuring consistent left alignment regardless of source HTML indentation.
                let cleanedText = rawText.split('\n')
                                    .map(line => line.trim())
                                    .filter(line => line.length > 0)
                                    .join('\n');

                let finalContent = cleanedText; // Default to original cleaned text

                // Step 2: Check for and apply key-value styling (only if it's not a delimiter line)
                if (cleanedText.trim() !== startDelimiter && cleanedText.trim() !== endDelimiter) {
                    const colonIndex = cleanedText.indexOf(':');

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
                if (cleanedText.trim() === startDelimiter || cleanedText.trim() === endDelimiter) {
                    node.classList.add('game-interface-delimiter');
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