// game-interface-script.js

document.addEventListener('DOMContentLoaded', function() {
    const startDelimiter = '_____________________';
    const endDelimiter = '¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯';

    // Select all paragraphs that might contain the game interface content.
    const allParagraphs = document.querySelectorAll('p.calibre5');

    let currentInterfaceParagraphs = [];
    let inInterfaceBlock = false;
    let firstParagraphOfBlock = null; // To store the first paragraph of a detected block

    // Iterate through the NodeList of paragraphs using a standard for loop for performance.
    for (let i = 0; i < allParagraphs.length; i++) {
        const p = allParagraphs[i];
        // Trim the entire paragraph text for delimiter detection
        const trimmedText = p.textContent.trim();

        if (trimmedText === startDelimiter) {
            // Found a start delimiter.
            // If we were already in a block (meaning the previous one wasn't properly closed),
            // process the existing collected block first.
            if (inInterfaceBlock && currentInterfaceParagraphs.length > 0) {
                processBlock(currentInterfaceParagraphs, firstParagraphOfBlock);
            }
            // Start a new block
            inInterfaceBlock = true;
            firstParagraphOfBlock = p; // Mark this paragraph as the anchor for insertion
            currentInterfaceParagraphs = [p]; // Start collecting paragraphs for this new block
        } else if (trimmedText === endDelimiter) {
            // Found an end delimiter.
            if (inInterfaceBlock) {
                currentInterfaceParagraphs.push(p); // Include the end delimiter in the block
                processBlock(currentInterfaceParagraphs, firstParagraphOfBlock); // Process the collected block
                // Reset for the next potential block
                inInterfaceBlock = false;
                currentInterfaceParagraphs = [];
                firstParagraphOfBlock = null;
            }
        } else if (inInterfaceBlock) {
            // Inside an interface block, collect the paragraph
            currentInterfaceParagraphs.push(p);
        }
    }

    // After the loop, check if any block was left unclosed at the end of the document.
    if (inInterfaceBlock && currentInterfaceParagraphs.length > 0) {
        processBlock(currentInterfaceParagraphs, firstParagraphOfBlock);
    }

    /**
     * Processes a collected block of paragraphs by wrapping them in a new div
     * and inserting it back into the DOM.
     * @param {Array<HTMLElement>} nodes - An array of paragraph elements belonging to the block.
     * @param {HTMLElement} firstNode - The first paragraph element of the block, used for determining insertion point.
     */
    function processBlock(nodes, firstNode) {
        if (!firstNode || nodes.length === 0) {
            return; // Guard against empty or invalid blocks
        }

        const parent = firstNode.parentNode;
        if (!parent) {
            console.warn("Skipping block processing: firstNode has no parent.", firstNode);
            return; // First node must have a parent to determine insertion point
        }

        const interfaceDiv = document.createElement('div');
        interfaceDiv.classList.add('game-interface');

        // Store the next sibling of the first node *before* detaching any nodes.
        // This is the reference point for where the new interfaceDiv will be inserted.
        const originalNextSibling = firstNode.nextSibling;

        // Use a DocumentFragment to minimize reflows during DOM manipulation.
        // All nodes are moved into the fragment first, then the fragment is appended once.
        const fragment = document.createDocumentFragment();

        // Move each node from its original parent to the fragment, then apply delimiter class.
        nodes.forEach(node => {
            // Ensure the node is still part of the expected parent before moving.
            if (node.parentNode === parent) {
                // === IMPORTANT CHANGE HERE: Clean text content before appending ===
                // Split the text by newlines, trim each individual line, and then join them back.
                // This removes any leading/trailing whitespace on each line, ensuring left alignment.
                let cleanedText = node.textContent.split('\n')
                                    .map(line => line.trim())
                                    .filter(line => line.length > 0) // Optionally remove lines that are entirely empty after trimming
                                    .join('\n');

                node.textContent = cleanedText;
                // ===================================================================

                // Apply delimiter class if it's a delimiter line (after cleaning text content)
                if (node.textContent.trim() === startDelimiter || node.textContent.trim() === endDelimiter) {
                    node.classList.add('game-interface-delimiter'); // Add class to hide delimiters via CSS
                }
                fragment.appendChild(node); // This automatically removes the node from its original parent.
            }
        });

        // Append the populated fragment to the new interface div.
        interfaceDiv.appendChild(fragment);

        // Insert the complete interface div back into the DOM at the original position.
        parent.insertBefore(interfaceDiv, originalNextSibling);
    }
});