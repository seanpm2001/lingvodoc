import itertools
import json
import re

from sqlalchemy import func, literal, tuple_

from lingvodoc.models import (
    DBSession as SyncDBSession,
    TranslationAtom,
    TranslationGist,
    Field,
    Entity,
    LexicalEntry,
    Dictionary,
    Language,
    DictionaryPerspectiveToField,
    DictionaryPerspective,
    PublishingEntity
)

from lingvodoc.schema.gql_holders import ResponseError
from sqlalchemy.orm import aliased
from pdb import set_trace as A


def get_json_tree(
        only_in_toc=False,
        l_group=None,
        l_title=None,
        p_offset=0,
        p_limit=10,
        p_id=None,
        debug_flag=False):

    result_dict = {}
    language_list = []
    cur_language_id = None
    cur_dictionary_id = None
    cur_perspective_id = None

    dictionary_title = None
    perspective_title = None

    # Getting set of cte
    (
        language_cte, dictionary_cte, perspective_cte, field_query

    ) = get_cte_set(only_in_toc, l_group, l_title, p_offset, p_limit, p_id)

    def id2str(id):
        return f'{id[0],id[1]}'

    # Getting perspective_id and etymology fields ids and names in cycle
    for (
        perspective_id,
        (xcript_fid, xcript_fname),
        (xlat_fid, xlat_fname)

    ) in fields_getter(field_query):

        # Init dictionary_id and language_id
        dictionary_id = cur_dictionary_id
        language_id = cur_language_id

        # Getting next perspective_title and dictionary_id
        if perspective_id != cur_perspective_id:
            (
                perspective_title,
                dictionary_cid,
                dictionary_oid

            ) = perspective_getter(perspective_cte, perspective_id)

            dictionary_id = (dictionary_cid, dictionary_oid)

        # Getting next dictionary_title and language_id
        if dictionary_id != cur_dictionary_id:
            (
                dictionary_title,
                language_cid,
                language_oid

            ) = dictionary_getter(dictionary_cte, dictionary_id)

            language_id = (language_cid, language_oid)

        # Getting next language_title
        if language_id != cur_language_id:
            (
                language_title,

            ) = language_getter(language_cte, language_id)

            lang_slot = result_dict[id2str(language_id)] = {}
            lang_slot['title'] = language_title

            # Logging processed languages
            language_list.append(language_title)

            cur_language_id = language_id

            if debug_flag:
                print(f"*** Language: {language_id} | {language_title}")

        # Once again check conditions for dictionary and perspective
        # and put the data into result_dict

        if dictionary_id != cur_dictionary_id:

            dict_slot = lang_slot[id2str(dictionary_id)] = {}
            dict_slot['title'] = dictionary_title

            cur_dictionary_id = dictionary_id

            if debug_flag:
                print(f"** Dictionary: {dictionary_id} | {dictionary_title}")

        if perspective_id != cur_perspective_id:

            pers_slot = dict_slot[id2str(perspective_id)] = {}
            pers_slot['title'] = perspective_title
            pers_slot['fields'] = [
                (xcript_fid, xcript_fname), (xlat_fid, xlat_fname)
            ]
            pers_slot['entities'] = {}

            cur_perspective_id = perspective_id

            if debug_flag:
                print(f"* Perspective: {perspective_id} | {perspective_title}\n")

        for (
            lex_id,
            xcript_text,
            xlat_text,
            linked_group

        ) in entities_getter(perspective_id, xcript_fid, xlat_fid):

            pers_slot['entities'][id2str(lex_id)] = (
                xcript_text, xlat_text, linked_group
            )

            if debug_flag:
                print(f"{xcript_fname}: {xcript_text}")
                print(f"{xlat_fname}: {xlat_text}")
                print(f"Cognate_groups: {str(linked_group)}\n")

    return json.dumps(result_dict), language_list


def perspective_getter(perspective_cte, perspective_id):
    return (
        SyncDBSession
            .query(
                perspective_cte.c.perspective_title,
                perspective_cte.c.dictionary_cid,
                perspective_cte.c.dictionary_oid)

            .filter(
                perspective_cte.c.perspective_cid == perspective_id[0],
                perspective_cte.c.perspective_oid == perspective_id[1])

            .one())

def dictionary_getter(dictionary_cte, dictionary_id):
    return (
        SyncDBSession
            .query(
                dictionary_cte.c.dictionary_title,
                dictionary_cte.c.language_cid,
                dictionary_cte.c.language_oid)

            .filter(
                dictionary_cte.c.dictionary_cid == dictionary_id[0],
                dictionary_cte.c.dictionary_oid == dictionary_id[1])

            .one())

def language_getter(language_cte, language_id):
    return (
        SyncDBSession
            .query(
                language_cte.c.language_title)

            .filter(
                language_cte.c.language_cid == language_id[0],
                language_cte.c.language_oid == language_id[1])

            .one())

# Getting cte for languages, dictionaries, perspectives and fields

def get_cte_set(only_in_toc, l_group, l_title, p_offset, p_limit, p_id):

    get_translation_atom = [
        TranslationGist.marked_for_deletion == False,
        TranslationAtom.parent_id == TranslationGist.id,
        func.length(TranslationAtom.content) > 0,
        TranslationAtom.marked_for_deletion == False ]

    def get_language_ids(name):
        nonlocal get_translation_atom
        return (
            SyncDBSession
                .query(
                    Language.client_id,
                    Language.object_id)
                .filter(
                    Language.translation_gist_id == TranslationGist.id,
                    *get_translation_atom,
                    func.lower(TranslationAtom.content) == name.lower())
                .all())

    # Getting root languages

    language_init = (
        SyncDBSession
            .query(
                Language,
                literal(0).label('level'))

            .filter(
                Language.marked_for_deletion == False))

    if not l_group and not l_title:
        language_init = language_init.filter(
            Language.parent_client_id == None,
            Language.parent_object_id == None)
    else:
        if l_group:
            if group_ids := get_language_ids(l_group):
                language_init = language_init.filter(
                    tuple_(Language.parent_client_id, Language.parent_object_id).in_(group_ids))
            else:
                raise ResponseError(message="No such language parent group in the database")
        if l_title:
            if title_ids := get_language_ids(l_title):
                language_init = language_init.filter(
                    tuple_(Language.client_id, Language.object_id).in_(title_ids))
            else:
                raise ResponseError(message="No such language group or title in the database")

    language_init = language_init.cte(recursive=True)

    prnLanguage = aliased(language_init)
    subLanguage = aliased(Language)

    # Recursively getting tree of languages

    language_step = language_init.union_all(
        SyncDBSession
            .query(
                subLanguage,
                (prnLanguage.c.level + 1).label("level"))

            .filter(
                subLanguage.parent_client_id == prnLanguage.c.client_id,
                subLanguage.parent_object_id == prnLanguage.c.object_id,
                subLanguage.marked_for_deletion == False))

    if_only_in_toc = [language_step.c.additional_metadata['toc_mark'] == 'true'] if only_in_toc else []

    language_cte = (
        SyncDBSession
            .query(
                language_step.c.client_id.label('language_cid'),
                language_step.c.object_id.label('language_oid'),
                func.array_agg(TranslationAtom.content).label('language_title'),
                func.min(language_step.c.level).label('language_level'))

            .filter(
                language_step.c.translation_gist_client_id == TranslationGist.client_id,
                language_step.c.translation_gist_object_id == TranslationGist.object_id,
                *get_translation_atom, *if_only_in_toc)

            .group_by(
                'language_cid',
                'language_oid')

            .cte())

    # Getting dictionaries with self titles

    dictionary_cte = (
        SyncDBSession
            .query(
                Dictionary.parent_client_id.label('language_cid'),
                Dictionary.parent_object_id.label('language_oid'),
                Dictionary.client_id.label('dictionary_cid'),
                Dictionary.object_id.label('dictionary_oid'),
                func.array_agg(TranslationAtom.content).label('dictionary_title'),
                func.min(language_cte.c.language_level).label('language_level'))

            .filter(
                Dictionary.parent_client_id == language_cte.c.language_cid,
                Dictionary.parent_object_id == language_cte.c.language_oid,
                Dictionary.marked_for_deletion == False,
                Dictionary.translation_gist_id == TranslationGist.id,
                *get_translation_atom)

            .group_by(
                'language_cid',
                'language_oid',
                'dictionary_cid',
                'dictionary_oid')

            .cte())

    # Getting perspectives with self titles

    perspective_cte = (
        SyncDBSession
            .query(
                DictionaryPerspective.parent_client_id.label('dictionary_cid'),
                DictionaryPerspective.parent_object_id.label('dictionary_oid'),
                DictionaryPerspective.client_id.label('perspective_cid'),
                DictionaryPerspective.object_id.label('perspective_oid'),
                func.array_agg(TranslationAtom.content).label('perspective_title'),
                func.min(dictionary_cte.c.language_level).label('language_level'))

            .filter(
                DictionaryPerspective.parent_client_id == dictionary_cte.c.dictionary_cid,
                DictionaryPerspective.parent_object_id == dictionary_cte.c.dictionary_oid,
                DictionaryPerspective.marked_for_deletion == False,
                DictionaryPerspective.translation_gist_id == TranslationGist.id,
                *get_translation_atom)

            .group_by(
                'dictionary_cid',
                'dictionary_oid',
                'perspective_cid',
                'perspective_oid')

            .order_by(
                'language_level',
                'perspective_cid',
                'perspective_oid')

            .offset(p_offset)
            .limit(p_limit if not p_id else None)
            .cte())

    # Getting fields with self title

    get_p_id = [
        DictionaryPerspectiveToField.parent_client_id == p_id[0],
        DictionaryPerspectiveToField.parent_object_id == p_id[1]
    ] if p_id else [
        DictionaryPerspectiveToField.parent_client_id == perspective_cte.c.perspective_cid,
        DictionaryPerspectiveToField.parent_object_id == perspective_cte.c.perspective_oid
    ]

    field_query = (
        SyncDBSession
            .query(
                DictionaryPerspectiveToField.parent_client_id,
                DictionaryPerspectiveToField.parent_object_id,
                Field.client_id.label('field_cid'),
                Field.object_id.label('field_oid'),
                func.array_agg(func.lower(TranslationAtom.content)).label('field_title'),
                func.min(DictionaryPerspectiveToField.position).label('field_position'),
                func.min(perspective_cte.c.language_level).label('language_level'))

            .filter(
                *get_p_id,
                DictionaryPerspectiveToField.marked_for_deletion == False,
                DictionaryPerspectiveToField.field_id == Field.id,
                Field.marked_for_deletion == False,
                Field.translation_gist_id == TranslationGist.id,
                *get_translation_atom, TranslationAtom.locale_id <= 2)

            .group_by(
                DictionaryPerspectiveToField.parent_client_id,
                DictionaryPerspectiveToField.parent_object_id,
                'field_cid', 'field_oid')

            .order_by(
                'language_level',
                DictionaryPerspectiveToField.parent_client_id,
                DictionaryPerspectiveToField.parent_object_id)

            .yield_per(100))

    return (
        language_cte,
        dictionary_cte,
        perspective_cte,
        field_query)

# Getting perspectives with transcription, translation and cognates

def fields_getter(field_query):

    def has_word(word, text):
        return bool(re.search(r'\b' + word + r'\b', text))

    # Group fields by perspective
    fields_by_perspective = itertools.groupby(field_query, key=lambda x: (x[0], x[1]))

    for perspective_id, fields_group in fields_by_perspective:

        # Sorting fields by position
        fields_list = sorted(list(fields_group), key=lambda x: x[5])

        xcript_fid, xlat_fid, xcript_fname, xlat_fname = [None] * 4
        with_cognates = False

        for _, _, field_cid, field_oid, title, _, _ in fields_list:

            title = "; ".join(title)

            if xcript_fid is None and not has_word("affix", title):
                if (has_word("transcription", title) or
                        has_word("word", title) or
                        has_word("транскрипция", title) or
                        has_word("слово", title) or
                        has_word("лексема", title) or
                        has_word("праформа", title)):
                    xcript_fid = (field_cid, field_oid)
                    xcript_fname = title

            if xlat_fid is None and not has_word("affix", title):
                if (has_word("translation", title) or
                        has_word("meaning", title) or
                        has_word("перевод", title) or
                        has_word("значение", title)):
                    xlat_fid = (field_cid, field_oid)
                    xlat_fname = title

            if ((field_cid, field_oid) == (66, 25)):
                with_cognates = True

            if xcript_fid and xlat_fid and with_cognates:
                break

        if xcript_fid and xlat_fid and with_cognates:
            yield (
                perspective_id,
                (xcript_fid, xcript_fname),
                (xlat_fid, xlat_fname))


def entities_getter(perspective_id, xcript_fid, xlat_fid):

    xcript_text = None
    xlat_text = None

    entities = (
        SyncDBSession
            .query(
                LexicalEntry.client_id,
                LexicalEntry.object_id,
                Entity.field_id,
                Entity.content)

            .filter(
                LexicalEntry.parent_id == perspective_id,
                Entity.parent_id == LexicalEntry.id,
                Entity.field_id.in_([xcript_fid, xlat_fid]),
                Entity.marked_for_deletion == False,
                Entity.client_id == PublishingEntity.client_id,
                Entity.object_id == PublishingEntity.object_id,
                PublishingEntity.published == True,
                PublishingEntity.accepted == True)

            .yield_per(100))

    entities_by_lex = itertools.groupby(entities, key=lambda x: (x[0], x[1]))

    for lex_id, entities_group in entities_by_lex:

        linked_group = (
            SyncDBSession
                .execute(
                    f'select * from linked_group(66, 25, {lex_id[0]}, {lex_id[1]})')
                .fetchall())

        # Preparing of linked_group for json-serialization
        linked_group = list(map(lambda x: tuple(x), linked_group))

        entities_by_field = itertools.groupby(entities_group, key = lambda x: (x[2], x[3]))

        for field_id, group in entities_by_field:

            field_text = [x[4] for x in group]

            if field_id == xcript_fid:
                xcript_text = field_text
            elif field_id == xlat_fid:
                xlat_text = field_text

        # Return current found lexical entry with perspective_id

        yield (
            lex_id,
            xcript_text,
            xlat_text,
            linked_group)