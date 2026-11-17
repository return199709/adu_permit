"""drawkit.permit - from a city's code to an intake questionnaire, a compliance check and a first drawing set.

    read    fetch a city's code pages and have Claude extract the rules into a DRAFT rule file
    review  a person approves each extracted rule against its quoted source
    intake  list the measurements, photos and documents needed for a project in that city
    check   test the owner's answers against the reviewed rules
    draw    generate a drawkit project (cover sheet, site and roof plan, floor plan) from the answers
"""
