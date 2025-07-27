document.addEventListener('DOMContentLoaded', function() {
    console.time('Chapter Insertion'); // Start performance timer

    const insertions = [];

    // 1. EFFICIENT NODE TRAVERSAL
    // Use TreeWalker for memory-efficient traversal on huge documents.
    // It doesn't create a large NodeList in memory like querySelectorAll.
    const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_ELEMENT,
        {
            acceptNode: function(node) {
                // This filter function is highly optimized. It checks the most
                // specific conditions first to fail fast.
                if (
                    node.tagName === 'DIV' &&
                    node.id.startsWith('calibre_link-') &&
                    node.classList.contains('calibre')
                ) {
                    return NodeFilter.FILTER_ACCEPT; // Found a match
                }
                return NodeFilter.FILTER_SKIP; // Continue walking
            }
        }
    );

    // 2. READ PHASE: GATHER ALL WORK
    // We iterate through the document once, gathering all the necessary information
    // without modifying the DOM. This avoids layout thrashing.
    let currentNode;
    while (currentNode = walker.nextNode()) {
        const match = currentNode.id.match(/calibre_link-(\d+)/);
        if (match && match[1]) {
            const chapterNumber = parseInt(match[1], 10) + 1;

            // Create the new element in memory (not attached to the DOM yet)
            const chapterDiv = document.createElement('div');
            chapterDiv.className = 'chapter';
            chapterDiv.textContent = `Chapter - ${chapterNumber}`;
            
            // Add the "work" to a list: the new element and its target location.
            insertions.push({
                target: currentNode,
                newNode: chapterDiv
            });
        }
    }

    // 3. WRITE PHASE: BATCH DOM MODIFICATIONS
    // Now, we perform all DOM manipulations in a tight loop. Modern browsers are
    // very good at optimizing a rapid series of changes into a single repaint.
    // We iterate backwards to avoid issues with changing element indices.
    for (let i = insertions.length - 1; i >= 0; i--) {
        const task = insertions[i];
        // 'afterend' inserts the newNode immediately after the target element.
        task.target.insertAdjacentElement('afterend', task.newNode);
    }

    console.timeEnd('Chapter Insertion'); // Stop timer and log duration
});