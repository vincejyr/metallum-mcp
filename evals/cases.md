# Metallum MCP eval: cases for review

Each prompt runs in headless Claude Code with only the `metallum` server attached, replaying recorded site data. A short appended system prompt asks the model to finish with a line `ANSWER: <answer>` (or `ANSWER: NOT FOUND`); graders read that line.

| # | id | tags | expected | tool check |
|---|---|---|---|---|
| 1 | `watchtower_year` | fact, easy | 1989 |  |
| 2 | `nedgravd_drummer` | multi_hop, easy | contains “Rostadmo” |  |
| 3 | `nedgravd_label` | fact, easy | contains “Headsplit” |  |
| 4 | `sabbat_japan_genre` | name_collision, medium | contains “black” + “thrash” |  |
| 5 | `morbid_saint_albums` | multi_hop, medium | 3 and “Spectrum of Death” |  |
| 6 | `lyric_search` | search, medium | contains “Leper Affinity” + “Opeth” |  |
| 7 | `review_score` | reviews, medium | 91 |  |
| 8 | `similar_nedgravd` | fact, easy | contains “Infester” |  |
| 9 | `coroner_pre1990_avg` | rating, medium | 91.2 (±0.5) |  |
| 10 | `bay_area_ranking` | rating, hard | contains “Vio-lence” | band_review_stats |
| 11 | `cult_shortlist` | rating, hard | exactly these 7: Slauter Xstroyes, Ostrogoth, Morbid Saint, Holy Terror, Realm, Watchtower, Znöwhite | band_review_stats |
| 12 | `sortilege_albums` | edge_case, hard | 2 |  |
| 13 | `metallica_pre1990_reviews` | big_discography, hard | VERIFY_AT_RECORDING |  |
| 14 | `thrash_total` | paging, medium | VERIFY_AT_RECORDING |  |
| 15 | `not_found` | edge_case, easy | contains “NOT FOUND” |  |
| 16 | `ambiguous_releases` | ambiguity, medium | judge: states its interpretation of “releases” |  |

## 1. watchtower_year

```text
What year did Watchtower release Control and Resistance?
```

## 2. nedgravd_drummer

```text
Who plays drums on Nedgravd's album Ascension?
```

## 3. nedgravd_label

```text
Which label is the Norwegian death metal band Nedgravd currently signed to?
```

## 4. sabbat_japan_genre

```text
What genre does the Japanese band Sabbat play, according to Metal Archives?
```

## 5. morbid_saint_albums

```text
How many full-length albums has Morbid Saint released, and which one has the most reviews on Metal Archives? Answer as '<count>; <album title>'.
```

## 6. lyric_search

```text
Which metal song's lyrics open with the words 'We entered winter'? Give the song and the band.
```

## 7. review_score

```text
What score did the reviewer hells_unicorn give Nedgravd's Ascension on Metal Archives? Answer with the percentage.
```

## 8. similar_nedgravd

```text
Which band do Metal Archives users rate as most similar to Nedgravd?
```

## 9. coroner_pre1990_avg

```text
What is the review-weighted average score of Coroner's full-length albums released before 1990? Answer as a percentage with one decimal.
```

## 10. bay_area_ranking

```text
Among Dark Angel, Vio-lence, Forbidden, Heathen and Death Angel, which band has the highest review-weighted average score across its full-length albums released before 1990?
```

## 11. cult_shortlist

```text
Of these bands - Slauter Xstroyes, Ostrogoth, Morbid Saint, Holy Terror, Realm, Watchtower, Znöwhite, Sacred Blade, Liege Lord, Brocas Helm - which have at most 3 full-length albums, at least 5 reviews across those albums, and a review-weighted average above 90% across them? List the qualifying band names separated by commas.
```

## 12. sortilege_albums

```text
How many distinct studio albums did the French band Sortilège release in the 1980s? Count an album released in two languages once.
```

## 13. metallica_pre1990_reviews

```text
How many reviews in total do Metallica's releases dated before 1990 have on Metal Archives (all release types)?
```

## 14. thrash_total

```text
How many bands does Metal Archives return for an advanced band search with genre 'thrash' and formation year up to 1989?
```

## 15. not_found

```text
What year was the metal band Zzyzxqwk Vorthrangul formed?
```

## 16. ambiguous_releases

```text
Of Holy Terror, Znöwhite and Realm, which have fewer than 4 releases?
```
