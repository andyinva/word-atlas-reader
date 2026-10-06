#!/usr/bin/env python3
"""
reader_help.py  -  help mode for the Word Atlas Reader

The ? button (or F1) turns the window into a help screen: the pointer
becomes a question mark, and resting it on any part of the window
shows a note saying what that part is.  Point at a column heading in
a grid and the note explains the column, the same explanations the
main program's help mode gives.  A click, Escape or ? leaves help mode.

HELP holds the notes for the Reader's own controls, keyed by the
"help" property each control carries.  COLUMN_HELP and COLUMN_PATTERNS
are copied from the main program's atlas_help.py with the function-word
entries written out, so the Reader stays free of the main program.
"""

import re

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

# The Reader's controls
HELP = {
    "help": "Help mode.  Press it (or F1), then point at anything in the window to read what it is.  "
            "Click, Escape or press ? again to leave.",
    "run": "Which run of the main program this page comes from.  A run is one pass of Word Atlas: its "
           "version, the build it used and when it started.  A dataset usually holds one run; a file "
           "that holds two can be compared with Results > Diff two runs.",
    "search": "Search every cell, section title and footer of the run for this text (case does not matter): "
              "a word, a Strong's number such as H1005 or G2962, a phrase.  Press Enter or the button; "
              "the hits appear on the Search tab, and double-clicking a hit opens its page at that table.  "
              "The arrow at the right lists earlier searches.",
    "filter": "Narrow the page list to titles containing this text: a book name, a chapter number, "
              "'Section', 'Compare'.",
    "pages": "The pages the run holds, grouped by kind: Book, Chapter, Section, Passage, Word, Kin, "
             "Testament, Compare.  Click one to show it on the Page and Table tabs.",
    "tabs": "The views of the chosen page: Page (as text), Table (one table as a grid), Search (hits), "
            "Results (the canon-wide questions from the Results menu) and Ask Claude.",
    "jump": "Jump to a section of the page: the text scrolls so that section's title is at the top.",
    "wrap": "Wrap long lines in the page text.  Off, the page is exactly as the main program's text file lays "
            "it out, and tables keep their columns; on, the long note lines fold to the window's width "
            "and tables may fold too.",
    "page_view": "The page as text, laid out by the same code the main program uses for its reports/*.txt "
                 "files: the title, the build line, the notes, then each section with its note, table and "
                 "footer.  File > Save page as text writes it out.",
    "table_box": "Which table of the page the grid shows.",
    "table_note": "The table's note: what it measures and how to read it.",
    "grid": "One table of the page as a grid.  Click a column heading to sort by it (numbers sort as "
            "numbers; a second click reverses).  Hover a row for the verses behind it, click it to see "
            "them in the status bar.  In help mode, point at a heading to read what the column is.",
    "table_footer": "The lines the main program printed under the table: its findings in words.",
    "search_grid": "The search hits: the page, the table's number, the row and column, and the cell.  A hit "
                   "in a section title or footer shows 'title' or 'footer' as its column.  Double-click a "
                   "hit to open its page at that table.",
    "results_view": "The answer to a Results menu question, laid out as atlas_results.py prints it.  "
                    "Save as text writes it out.",
    "question": "A question about the dataset, in plain words.  Claude answers it by writing SQL queries "
                "against the open file (read-only) and reading the rows back, then says where each figure "
                "came from.  The box above lists earlier questions.",
    "past_questions": "Earlier questions, then a set of starter questions to try; choose one to put it in the "
                      "box.  The first starter, 'What can I ask about this dataset?', has Claude describe what "
                      "the file holds and suggest questions of its own.",
    "ask": "Send the question to Claude with your API key (File > Claude settings).  Each question costs a "
           "few cents on your own account; only the rows Claude asks for travel, never the whole file.",
    "copy_prompt": "No API key?  This puts the question, the schema and the open page on the clipboard as a "
                   "prompt to paste into claude.ai or any assistant.",
    "answer": "Claude's answer.  The figures come from the queries listed below; check them against the "
              "page and table it names.",
    "queries": "The SQL queries Claude ran to answer, in order, including any the Reader refused (only a "
               "single SELECT may run).",
    "title": "The section's title: its number on the page, then what it measures.",
}

# The column headings of the tables, copied from the main program
COLUMN_HELP = {'-i/-nu': '-i/-nu (H9020, H9030, H9040, H9025, H9035, H9045): first person suffixes (my, me, our, '
           'us).  Occurrences per 1,000 tokens of the text (King James tokens for a Greek book, '
           'Hebrew elements for a Hebrew one).',
 '-ka': '-ka (H9021, H9022, H9031, H9032, H9041, H9042, H9026, H9027, H9036, H9037, H9046, H9047): '
        'second person suffixes (your, you).  Occurrences per 1,000 tokens of the text (King James '
        'tokens for a Greek book, Hebrew elements for a Hebrew one).',
 '-o/-am': '-o/-am (H9023, H9024, H9033, H9034, H9043, H9044, H9028, H9029, H9038, H9039, H9048, '
           'H9049): third person suffixes (his, her, him, them).  Occurrences per 1,000 tokens of '
           'the text (King James tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'Bible/1000': 'How often the word occurs per 1,000 words across the whole Bible, for comparison '
               'with the column to its left.',
 'Delta': "Burrows' Delta: how far apart two texts are in their habits with the small words "
          '(particles, conjunctions, prepositions, pronouns), each rate as a z-score against the '
          "New Testament's books, then the mean absolute difference.  0 would be identical; the "
          "footer's yardsticks say what two different books, and the two halves of one book, "
          'typically score.',
 'English echo': 'An echo section 4 found across the testaments by the King James wording, grown '
                 'to the run the two verses share in English.',
 'Greek shared': 'The longest run of Greek, by root, that the two verses share; empty when they '
                 'share no word.',
 'I': 'I (H589, H595): I (ani, anoki).  Occurrences per 1,000 tokens of the text (King James '
      'tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'I/me': 'I/me (G1473, G3450, G3427, G3165, G1691, G1698, G1700): first person singular.  '
         'Occurrences per 1,000 tokens of the text (King James tokens for a Greek book, Hebrew '
         'elements for a Hebrew one).',
 'KJV glosses': "The English words the King James translators used for this word, from Strong's "
                'dictionary.',
 'New Testament': 'The New Testament verses holding the echo.',
 'Septuagint': 'In 1f, how many times the Septuagint uses the word; in 4e, the Septuagint verses '
               'holding the echo, with the Rahlfs numbering in brackets where it differs from the '
               'English.',
 'Septuagint home (any book)': 'The Septuagint book where the word is commonest, with its count '
                               "there, searched over the whole Septuagint whatever the table's far "
                               "side is; 'not in the Septuagint' when no book of it has the word.",
 'Septuagint/10k': 'How often the word occurs per 10,000 content words of the Septuagint (the '
                   'whole of it, or the Septuagint books of the kind when the table says so).',
 'ad': 'ad (H5704): until.  Occurrences per 1,000 tokens of the text (King James tokens for a '
       'Greek book, Hebrew elements for a Hebrew one).',
 'al': 'al (H5921): upon.  Occurrences per 1,000 tokens of the text (King James tokens for a Greek '
       'book, Hebrew elements for a Hebrew one).',
 'al (not)': 'al (not) (H408): not (prohibition).  Occurrences per 1,000 tokens of the text (King '
             'James tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'alla': 'alla (G235): but.  Occurrences per 1,000 tokens of the text (King James tokens for a '
         'Greek book, Hebrew elements for a Hebrew one).',
 'also in NT': 'Other New Testament verses holding the same run: a synoptic parallel, or a '
               'formula.',
 'also in Septuagint': 'Other Septuagint verses holding the same run.',
 'asher': 'asher (H834): who, which, that.  Occurrences per 1,000 tokens of the text (King James '
          'tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'at the seams': "How many of the refrain's chapters close or open a section of the book.  A "
                 "refrain found only at the seams marks the book's divisions, as 'amen and amen' "
                 'closes Books I, II and III of the Psalter.',
 'autos': 'autos (G846): he, she, it, same.  Occurrences per 1,000 tokens of the text (King James '
          'tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'bar': 'A bar for the per-1000 figure, so the row can be read at a glance.',
 'be-': 'be- (H9003): in.  Occurrences per 1,000 tokens of the text (King James tokens for a Greek '
        'book, Hebrew elements for a Hebrew one).',
 'books': 'Reach: how many books the word occurs in, out of the books it could reach: 39 for a '
          'Hebrew number, 27 for a Greek one, 66 for an English stem.',
 'both': 'Verses with a parallel in both partner books: for a Gospel, the triple tradition.',
 'chapter': "The chapter.  Double-click to open the chapter's page.",
 'chapters': 'The chapters of the book the refrain appears in.',
 'chief partners (by weight)': "The two books this chapter's echoes point to most, by weight.",
 'content': 'How many distinct content words (not particles, articles, pronouns or conjunctions) '
            'the two places share in the run; a quotation needs three.',
 'count': 'Weight: how many times the word occurs at this scale.',
 'de': 'de (G1161): but, and.  Occurrences per 1,000 tokens of the text (King James tokens for a '
       'Greek book, Hebrew elements for a Hebrew one).',
 'deepest': 'The chapter where the word reaches its depth.',
 'deepest at': "The chapter where the word reaches its depth.  Click for the word's verses there.",
 'deepest/1000 at': "The section where the word is thickest for the section's length.",
 'depth': 'Depth: the highest keyness the word reaches in any one chapter, how thickly it piles up '
          'in its one deepest place.  Reach is horizontal, depth vertical.',
 'depth/1000': 'The section depth (keyness) per 1,000 words of the section: the same figure with '
               "the section's size removed, so a large part does not win by being large.",
 'dia': 'dia (G1223): through.  Occurrences per 1,000 tokens of the text (King James tokens for a '
        'Greek book, Hebrew elements for a Hebrew one).',
 'echo': 'A formula of three or more words found in this book and at least one other, rare enough '
         'to mean something (at most six verses Bible-wide).',
 'echo (Greek)': "The run of Greek words the two places share, as this book's text spells it.  "
                 "Matched by root (Strong's number), so the forms may differ between the two "
                 'places.',
 'echoes': 'How many distinct echoes are shared, or fall in the chapter.',
 'ei': 'ei (G1487): if.  Occurrences per 1,000 tokens of the text (King James tokens for a Greek '
       'book, Hebrew elements for a Hebrew one).',
 'eis': 'eis (G1519): into.  Occurrences per 1,000 tokens of the text (King James tokens for a '
        'Greek book, Hebrew elements for a Hebrew one).',
 'ek': 'ek (G1537): out of.  Occurrences per 1,000 tokens of the text (King James tokens for a '
       'Greek book, Hebrew elements for a Hebrew one).',
 'el': 'el (H413): to, toward.  Occurrences per 1,000 tokens of the text (King James tokens for a '
       'Greek book, Hebrew elements for a Hebrew one).',
 'elsewhere': 'The verses of other books holding the echo, with their books.',
 'en': 'en (G1722): in.  Occurrences per 1,000 tokens of the text (King James tokens for a Greek '
       'book, Hebrew elements for a Hebrew one).',
 'et': 'et (H853): object marker.  Occurrences per 1,000 tokens of the text (King James tokens for '
       'a Greek book, Hebrew elements for a Hebrew one).',
 'formula': "A set phrase of two to five words that recurs in the text.  On a Strong's build it is "
            'a run of roots, found however its words are spelled, and shown in its commonest '
            'wording here.  Click for the verses holding it, in every spelling.',
 'found by': "'roots' when the kin was found by shared Strong's numbers, within the testament; "
             "'English' when it was found across the testaments by the English stems of the words, "
             'since a Hebrew root never matches a Greek one.  An English row rests on the '
             "translators' wording.",
 'gam': 'gam (H1571): also.  Occurrences per 1,000 tokens of the text (King James tokens for a '
        'Greek book, Hebrew elements for a Hebrew one).',
 'gap': 'How many chapters apart the chapter and its partner are.  Neighbours share phrasing '
        'because the story continues; a wide gap means the author came back to the same wording '
        'later.',
 'gar': 'gar (G1063): for.  Occurrences per 1,000 tokens of the text (King James tokens for a '
        'Greek book, Hebrew elements for a Hebrew one).',
 'gloss': "The TAGNT's word-for-word English of the run, from the New Testament side of the match.",
 'grade': "'quotation' marks an echo of five or more words found in exactly two verses of the "
          "whole Bible, one here and one there: the strongest kind of evidence the table has.  'by "
          "English' marks an echo across the testaments that meets the same test by wording alone: "
          "weaker, since the translators' idiom can make it.",
 'ha-': 'ha- (H9009): the (article).  Occurrences per 1,000 tokens of the text (King James tokens '
        'for a Greek book, Hebrew elements for a Hebrew one).',
 'hapaxes': "The book's roots used once in the whole testament (a root of one testament never "
            'occurs in the other, so a testament hapax is a Bible hapax).',
 'hapaxes/1000': 'Hapaxes per 1,000 words of the book.',
 'here': 'The verses of this book holding the echo.',
 'here/10k': "How often the word occurs per 10,000 content words of this book's Greek text.",
 'hina': 'hina (G2443): in order that.  Occurrences per 1,000 tokens of the text (King James '
         'tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'hinneh': 'hinneh (H2009, H2005): behold.  Occurrences per 1,000 tokens of the text (King James '
           'tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'home book': 'The book that prefers this word most, by keyness against the rest of the testament.',
 'home words (count of testament)': 'The six words most at home in the book, best first, each with '
                                    "the book's count of the word and the testament's total.",
 'hos': 'hos (G3739): who, which.  Occurrences per 1,000 tokens of the text (King James tokens for '
        'a Greek book, Hebrew elements for a Hebrew one).',
 'hoti': 'hoti (G3754): that, because.  Occurrences per 1,000 tokens of the text (King James '
         'tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'hu/hi': 'hu/hi (H1931): he, she, it.  Occurrences per 1,000 tokens of the text (King James '
          'tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'im': 'im (H518): if.  Occurrences per 1,000 tokens of the text (King James tokens for a Greek '
       'book, Hebrew elements for a Hebrew one).',
 'in home': 'How many times the word occurs in its home book.',
 'in order': 'How many of those shared words come in the same order in both verses.',
 'in the rest of the Bible': "The same word's neighbors everywhere except this book, for "
                             'comparison with the left-hand side.',
 'in time': "'(disputed)' means the critical dates in CRITICAL_DATES would put the partner on the "
            'other side; the footer of 4a gives both datings.  Whether the partner is '
            'conventionally dated earlier, later or about the same time as this book (dates in '
            'atlas_text.py, disputed for many books).',
 'kai': 'kai (G2532): and.  Occurrences per 1,000 tokens of the text (King James tokens for a '
        'Greek book, Hebrew elements for a Hebrew one).',
 'kata': 'kata (G2596): according to.  Occurrences per 1,000 tokens of the text (King James tokens '
         'for a Greek book, Hebrew elements for a Hebrew one).',
 'ke-': 'ke- (H9004): like, as.  Occurrences per 1,000 tokens of the text (King James tokens for a '
        'Greek book, Hebrew elements for a Hebrew one).',
 'keyness': 'How much more often the word appears here than the rest of the Bible would predict '
            '(log-likelihood).  Above 10.8 is very unlikely by chance; a negative value means '
            'rarer here than expected.',
 'keyness (group)': "Keyness measured against the other books of this book's own kind, the "
                    'baseline group metadata.db gives it (a prophet against the prophets, an '
                    'epistle against the epistles), with the book left out of its own baseline.  A '
                    'word merely common in the kind falls; what remains sets the book apart from '
                    'its peers.  A row is shown only at 6.63 or above, the 1 percent line of the '
                    'measure, so a short book has a short table rather than rows of words used at '
                    "the kind's own rate.  Change the group in the books table of metadata.db.",
 'keyness (testament)': "The same word's keyness against the rest of its testament, section 1's "
                        'figure, so the two baselines can be read side by side.',
 'ki': 'ki (H3588): for, because, that.  Occurrences per 1,000 tokens of the text (King James '
       'tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'kin verses': 'How many pairs of verses, one in each chapter, share three or more rare words.',
 'kind': "'near' when the partner is two chapters away, which may be either.  'adjacent' when the "
         "partner is the next chapter along (the story continuing), 'doublet?' when the two are "
         'three or more chapters apart (a passage told twice, a candidate to read side by side), '
         'blank in between.',
 'kol': 'kol (H3605): all, every.  Occurrences per 1,000 tokens of the text (King James tokens for '
        'a Greek book, Hebrew elements for a Hebrew one).',
 'le-': 'le- (H9005): to, for.  Occurrences per 1,000 tokens of the text (King James tokens for a '
        'Greek book, Hebrew elements for a Hebrew one).',
 'leading words (keyness against the rest of the book)': 'The words most key to the section '
                                                         'against the rest of the same book, with '
                                                         'count and keyness: what this part talks '
                                                         'about that the others do not.',
 'leaning': "The Septuagint's rate for the word divided by the rest of the New Testament's: how "
            "far the word belongs to the Greek Bible rather than to the New Testament's common "
            "stock.  'only here' when the rest of the New Testament never uses it.",
 'lemma': 'The Greek word in its dictionary form, as the tagging gives it.',
 'lo': 'lo (H3808): not.  Occurrences per 1,000 tokens of the text (King James tokens for a Greek '
       'book, Hebrew elements for a Hebrew one).',
 'me': 'me (G3361): not (subjunctive).  Occurrences per 1,000 tokens of the text (King James '
       'tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'mi-': 'mi- (H9006): from.  Occurrences per 1,000 tokens of the text (King James tokens for a '
        'Greek book, Hebrew elements for a Hebrew one).',
 'neighbor': 'A word that falls within the window of the head word, inside the same verse, more '
             'often than chance would put it there.  Double-click to open it.',
 'neither': "Verses with a parallel in neither partner: this book's own material.",
 'note': "On a refrains table: 'names' when every content word of the refrain is a proper name "
         '(Baruch the son of Neriah), a cast list rather than a formula.  On a signature words '
         "table the note column carries 'local', the renderings count and 'local rendering'.",
 'obs/exp': 'Observed against expected: the echoes shared, against how many would be expected from '
            "the partner's size alone.  Well above 1 is the interesting case.  In brackets and "
            "marked 'few' when it rests on fewer than twenty echoes: a small book with a few "
            'shared idioms always posts a high ratio.',
 'of testament': 'How many times the word occurs in the whole testament.',
 'once here': "The book's roots used once in the book.",
 'once here (share)': "Those as a share of all the book's roots.",
 'original': "The Hebrew or Greek word behind the number, from Strong's dictionary.",
 'original word': "The Hebrew or Greek word behind the number, from Strong's dictionary.",
 'ou': 'ou (G3756): not.  Occurrences per 1,000 tokens of the text (King James tokens for a Greek '
       'book, Hebrew elements for a Hebrew one).',
 'oun': 'oun (G3767): therefore.  Occurrences per 1,000 tokens of the text (King James tokens for '
        'a Greek book, Hebrew elements for a Hebrew one).',
 'own roots': "The book's roots found in no other book of the testament, used once or many times: "
              "Hebrews' are about 150, the most of any book its size.",
 'own/1000': 'Own roots per 1,000 words of the book.',
 'partner': 'The chapter of the same book this chapter shares the most rare phrasing with.',
 'partner book': 'A book this one shares echoes with.  Double-click to open its page.',
 'pas': 'pas (G3956): all, every.  Occurrences per 1,000 tokens of the text (King James tokens for '
        'a Greek book, Hebrew elements for a Hebrew one).',
 'per 100 words': 'Echo weight per 100 words of the chapter, so long and short chapters compare.',
 'per 1000': 'Occurrences per 1,000 words of the book, so long and short books compare.',
 'per 1000 words of partner': 'Echo weight per 1,000 words of the partner book.',
 'phrases': 'How many rare phrases (three or more words, in at most twelve verses of the book) the '
            'two chapters share; the weight beside it is their summed rarity.',
 'points to': "Which chapters of the partner books this chapter's echoes lead to: each chief "
              "partner's best chapter, then the next best, three in all, each carrying at least a "
              "tenth of the chapter's echo weight.  A run of rising chapter numbers down the "
              "column shows the book following its partner's order; the footer states the runs.",
 'pros': 'pros (G4314): to, toward.  Occurrences per 1,000 tokens of the text (King James tokens '
         'for a Greek book, Hebrew elements for a Hebrew one).',
 'pull': 'How strongly the head word draws this neighbor: how much more often they meet than '
         'chance predicts (log-likelihood).  Bigger is stronger.',
 'quotation grade': "How many of the partner's echoes are quotation grade: five or more words in "
                    'exactly two verses of the Bible, one here and one there.  Echoes that meet '
                    'the test only by English wording across the testaments are counted apart, as '
                    "'+N by English'.",
 'rarest echoes (here -> there)': "The partner's three rarest echoes (summed rarity of their "
                                  'words), each with the verse here and the verse there; (q) marks '
                                  'quotation grade.  One echo per verse pair.  Click the row for '
                                  'the verses on both sides.',
 'reach': "Reach: how widely the word is spread, here as the percent of the book's chapters it "
          'occurs in.',
 'refrain': 'A phrase of three or more words that recurs in three or more chapters of the book: '
            "the book's own refrain, set aside from the chapter map so it does not fill many cells "
            'at once.',
 'rest': 'How many verses hold the formula in the rest of the Bible.',
 'rest of NT': 'How many times the rest of the Greek New Testament uses the word.',
 'rest of NT/10k': 'How often the word occurs per 10,000 content words of the rest of the Greek '
                   'New Testament.',
 'rest/1000': 'How often the word occurs per 1,000 words in the text it is compared with: the rest '
              "of its own testament for a Strong's number (a Greek word cannot occur in the Old "
              'Testament), the rest of the Bible for an English stem.',
 'root': "A root behind the typed word: its spelling and Strong's number.  Double-click to open "
         "that root's page.",
 'roots/1000': 'Distinct roots per 1,000 words, a type-to-token figure; falls as a book grows, so '
               'compare books of like size.',
 'run': "What a run of consecutive chapters of this row's size, cut from the testament's other "
        'books, typically gives for the rate to its left (the median over every such run).  A rate '
        'well above its run figure is richness; a rate near it is size.',
 'score': "The chapter's kin score: the summed rarity of the words its verses share with verses "
          'here, raised when they come in the same order.',
 'second home': 'The book that prefers the word next most, with its count there.',
 'second partner': 'The next chapter of the book by shared weight, with the weight.',
 'section': 'A part of the book as atlas_sections.py divides it (the five books of the Psalter, '
            "Ezekiel's four parts); edit that file to change the divisions.",
 'sections': "Which sections of the book (its main division in atlas_sections.py) the refrain's "
             "chapters fall in: 'all in' one section, or 'spans' several.  A refrain that never "
             'crosses a proposed seam is evidence for the seam.',
 'shadow': "Shadow: the summed pull of all the word's neighbors at this scale, its total influence "
           'over the words around it.',
 'share': "The home book's count as a share of the testament's: 100% means the word occurs nowhere "
          'else in the testament.',
 'shared': 'How many rare words the strongest pair of verses shares.',
 'spelled here as': 'The English spellings this text uses for the root, commonest first, with '
                    'counts.',
 'spelled in the Bible': 'The English spellings the whole Bible uses for the root, commonest '
                         'first, with counts.',
 'spread': 'Keyness scaled by the share of chapters the word reaches, so a word that lives in one '
           'chapter scores less than one spread through the book.',
 'strongest pair': 'The pair of verses (one here, one there) that scores highest.',
 'strongest shared phrase': 'The shared phrase that weighs most, in its commonest wording.',
 'test': "What the Greek says of an echo the English found: 'departs' (two words or fewer in "
         "common), a quotation not in the Septuagint's words or an echo the translators' English "
         "made; 'short run', Greek that agrees for fewer words than 4e needs; 'formula', a run 4e "
         "set aside as the language's common stock; 'no Greek verse mapped', a Septuagint verse "
         'the catalogue has not placed.',
 'text': 'The opening words of the verse.',
 'they': 'they (H1992, H2007): they.  Occurrences per 1,000 tokens of the text (King James tokens '
         'for a Greek book, Hebrew elements for a Hebrew one).',
 'thou': 'thou (H859): you (singular).  Occurrences per 1,000 tokens of the text (King James '
         'tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'times': 'How many times the formula occurs here, counting repeats within a verse.',
 'tokens': 'Every King James word of the text, stop words included: the denominator of the '
           'function-word rates.',
 'verse': 'The verse of this chapter.  Click for the verse and its parallels in full.',
 'verses': 'How many verses hold the formula (or, in a sharing table, how many verses the chapter '
           'has).',
 'wa-': 'wa- (H9001): vav of the narrative verb chain (wayyiqtol).  Occurrences per 1,000 tokens '
        'of the text (King James tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'we': 'we (H587, H580): we.  Occurrences per 1,000 tokens of the text (King James tokens for a '
       'Greek book, Hebrew elements for a Hebrew one).',
 'we-': 'we- (H9002): and (the plain conjunction).  Occurrences per 1,000 tokens of the text (King '
        'James tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'we/us': 'we/us (G2249, G2257, G2254, G2248): first person plural.  Occurrences per 1,000 tokens '
          'of the text (King James tokens for a Greek book, Hebrew elements for a Hebrew one).',
 'weight': 'Weight: occurrences, or for echoes the summed rarity of the words involved (a rare '
           'word weighs more than a common one).',
 'where': 'The books the formula occurs in, most first.',
 'with a parallel': 'How many verses of the chapter have a verse-level parallel in the other book '
                    '(three content words in the same order, 30% of the shorter verse).',
 'word': "The word, as the atlas counts it: its commonest spelling, then its root.  A Strong's "
         'number after the word means every spelling of that Hebrew or Greek word is counted '
         "together.  Double-click to open the word's page.",
 'words': 'How many words the book has in all (or how many verses hold the formula).',
 'ye/you': 'ye/you (G5210, G5216, G5213, G5209): second person plural.  Occurrences per 1,000 '
           'tokens of the text (King James tokens for a Greek book, Hebrew elements for a Hebrew '
           'one).',
 '{words shared}': 'The rare words the strongest pair shares, in the order of the verse here; a '
                   'set, so { } brackets.'}

# Patterns for headings that carry a book or scale name
COLUMN_PATTERNS = [
    (re.compile(r"^(.+)/1000$"), "How often the word occurs per 1,000 words of {0}."),
    (re.compile(r"^in (.+)$"), "The head word's neighbors inside {0}: the neighbor, how many "
                               "times they meet, and the pull between them."),
    (re.compile(r"^(.+) only$"), "Verses with a parallel in {0} but not in the other partner."),
    (re.compile(r"^spelled in (.+)$"), "The English spellings used for the root in {0}, commonest first, with counts."),
]



def column_help(heading, section_title=""):
    """The help text for one column heading, or a plain fallback."""
    if heading in COLUMN_HELP:
        return COLUMN_HELP[heading]
    for pattern, text in COLUMN_PATTERNS:
        m = pattern.match(heading)
        if m:
            return text.format(m.group(1))
    if heading and heading[0].isdigit() or ":" in heading:
        return "A verse reference: the chapter and verse this parallel is in."
    return f"The {heading or 'column'} of this table."




class HelpNote(QLabel):
    """The floating note that follows the pointer in help mode."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setWordWrap(True)
        self.setMaximumWidth(440)
        self.setStyleSheet("QLabel { background-color: #fffbe6; color: #202020; "
                           "border: 1px solid #b0a060; padding: 6px 8px; font-size: 12px; }")

    def show_at(self, text, global_pos):
        """Show the note just below and right of a point, kept on screen."""
        if text != self.text():
            self.setText(text)
            self.adjustSize()
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x, y = global_pos.x() + 16, global_pos.y() + 20
        if x + self.width() > area.right():
            x = max(area.left(), global_pos.x() - self.width() - 8)
        if y + self.height() > area.bottom():
            y = max(area.top(), global_pos.y() - self.height() - 8)
        self.move(QPoint(x, y))
        if not self.isVisible():
            self.show()


class HelpMode(QObject):
    """
    Turns the window into a help screen: in help mode the pointer is a
    question mark, and resting it on any part of the window shows a
    note about that part.  Clicks are swallowed (and end help mode) so
    the user can point at buttons without pressing them.
    """

    def __init__(self, window, button):
        super().__init__(window)
        self.window = window
        self.button = button          # the checkable "?" button
        self.note = HelpNote()
        self.active = False
        QApplication.instance().installEventFilter(self)

    # -- switching on and off ----------------------------------------------------

    def set_active(self, on):
        """Enter or leave help mode."""
        if on == self.active:
            return
        self.active = on
        if on:
            QApplication.setOverrideCursor(Qt.CursorShape.WhatsThisCursor)
            self.window.statusBar().showMessage("Help mode: point at anything; click, Escape or ? to leave")
        else:
            QApplication.restoreOverrideCursor()
            self.note.hide()
            self.window.statusBar().clearMessage()
        if self.button.isChecked() != on:
            self.button.setChecked(on)

    # -- the event filter ------------------------------------------------------------

    def eventFilter(self, obj, event):
        if not self.active:
            return False
        kind = event.type()
        if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.set_active(False)
            return True
        if kind == QEvent.Type.MouseButtonPress:
            # A click on the ? button itself is left to the button (it
            # toggles help off); any other click just leaves help mode
            if obj is self.button or (isinstance(obj, QWidget) and self.button.isAncestorOf(obj)):
                return False
            self.set_active(False)
            return True
        if kind in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            return isinstance(obj, QWidget) and obj is not self.button
        if kind == QEvent.Type.MouseMove and isinstance(obj, QWidget):
            pos = event.globalPosition().toPoint()
            self.describe(QApplication.widgetAt(pos), pos)
            return False
        return False

    # -- composing the note --------------------------------------------------------------

    def describe(self, widget, global_pos):
        """Show the help for the widget under the pointer, if any."""
        text = self.text_for(widget, global_pos)
        if text:
            self.note.show_at(text, global_pos)
        else:
            self.note.hide()

    def text_for(self, widget, global_pos):
        """Walk up from a widget to the first one that can explain itself."""
        w = widget
        while w is not None:
            # Tables, maps and bars compose their note from the pointer's place
            composer = getattr(w, "help_at", None)
            if callable(composer):
                text = composer(w.mapFromGlobal(global_pos))
                if text:
                    return text
            key = w.property("help")
            if key:
                return HELP.get(key, key)     # a key into HELP, or a literal text
            w = w.parentWidget()
        return ""
